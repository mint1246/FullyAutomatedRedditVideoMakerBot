import re
import requests
import praw
from praw.models import MoreComments
from prawcore.exceptions import ResponseException
import json


from utils import settings
from utils.ai_methods import sort_by_similarity
from utils.console import print_step, print_substep
from utils.posttextparser import posttextparser
from utils.subreddit import get_subreddit_undone
from utils.videos import check_done
from utils.voice import sanitize_text

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"  # Replace with the actual Groq API URL

def get_subreddit_threads(POST_ID: str):
    """
    Returns a list of threads from the AskReddit subreddit.
    """

    print_substep("Logging into Reddit.")

    content = {}
    if settings.config["reddit"]["creds"]["2fa"]:
        print("\nEnter your two-factor authentication code from your authenticator app.\n")
        code = input("> ")
        print()
        pw = settings.config["reddit"]["creds"]["password"]
        passkey = f"{pw}:{code}"
    else:
        passkey = settings.config["reddit"]["creds"]["password"]

    username = settings.config["reddit"]["creds"]["username"]
    if str(username).casefold().startswith("u/"):
        username = username[2:]

    try:
        reddit = praw.Reddit(
            client_id=settings.config["reddit"]["creds"]["client_id"],
            client_secret=settings.config["reddit"]["creds"]["client_secret"],
            user_agent="Accessing Reddit threads",
            username=username,
            passkey=passkey,
            check_for_async=False,
        )
    except ResponseException as e:
        if e.response.status_code == 401:
            print("Invalid credentials - please check them in config.toml")
    except Exception as e:
        print("Something went wrong...", e)

    print_step("Getting subreddit threads...")
    similarity_score = 0
    if not settings.config["reddit"]["thread"]["subreddit"]:
        try:
            subreddit = reddit.subreddit(
                re.sub(r"r\/", "", input("What subreddit would you like to pull from? "))
            )
        except ValueError:
            subreddit = reddit.subreddit("askreddit")
            print_substep("Subreddit not defined. Using AskReddit.")
    else:
        sub = settings.config["reddit"]["thread"]["subreddit"]
        print_substep(f"Using subreddit: r/{sub} from TOML config")
        subreddit_choice = sub
        if str(subreddit_choice).casefold().startswith("r/"):
            subreddit_choice = subreddit_choice[2:]
        subreddit = reddit.subreddit(subreddit_choice)

    if POST_ID:
        submission = reddit.submission(id=POST_ID)
    elif (settings.config["reddit"]["thread"]["post_id"] and
          len(str(settings.config["reddit"]["thread"]["post_id"]).split("+")) == 1):
        submission = reddit.submission(id=settings.config["reddit"]["thread"]["post_id"])
    elif settings.config["ai"]["ai_similarity_enabled"]:
        threads = subreddit.hot(limit=50)
        keywords = settings.config["ai"]["ai_similarity_keywords"].split(",")
        keywords = [keyword.strip() for keyword in keywords]
        keywords_print = ", ".join(keywords)
        print(f"Sorting threads by similarity to the given keywords: {keywords_print}")
        threads, similarity_scores = sort_by_similarity(threads, keywords)
        submission, similarity_score = get_subreddit_undone(
            threads, subreddit, similarity_scores=similarity_scores
        )
    else:
        threads = subreddit.hot(limit=25)
        submission = get_subreddit_undone(threads, subreddit)

    if submission is None:
        return get_subreddit_threads(POST_ID)

    elif not submission.num_comments and settings.config["settings"]["storymode"] == "false":
        print_substep("No comments found. Skipping.")
        exit()

    submission = check_done(submission)

    upvotes = submission.score
    ratio = submission.upvote_ratio * 100
    num_comments = submission.num_comments
    threadurl = f"https://new.reddit.com/{submission.permalink}"

    print_substep(f"Video will be: {submission.title} :thumbsup:", style="bold green")
    print_substep(f"Thread url is: {threadurl} :thumbsup:", style="bold green")
    print_substep(f"Thread has {upvotes} upvotes", style="bold blue")
    print_substep(f"Thread has a upvote ratio of {ratio}%", style="bold blue")
    print_substep(f"Thread has {num_comments} comments", style="bold blue")
    if similarity_score:
        print_substep(
            f"Thread has a similarity score up to {round(similarity_score * 100)}%",
            style="bold blue",
        )

    content["thread_url"] = threadurl
    content["thread_title"] = submission.title
    content["thread_id"] = submission.id
    content["is_nsfw"] = submission.over_18
    content["comments"] = []
    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 1:
            content["thread_post"] = posttextparser(submission.selftext)
        else:
            content["thread_post"] = submission.selftext
    else:
        for top_level_comment in submission.comments:
            if isinstance(top_level_comment, MoreComments):
                continue

            if top_level_comment.body in ["[removed]", "[deleted]"]:
                continue
            if not top_level_comment.stickied:
                sanitised = sanitize_text(top_level_comment.body)
                if not sanitised or sanitised == " ":
                    continue
                if len(top_level_comment.body) <= int(settings.config["reddit"]["thread"]["max_comment_length"]):
                    if len(top_level_comment.body) >= int(settings.config["reddit"]["thread"]["min_comment_length"]):
                        if (top_level_comment.author is not None
                                and sanitize_text(top_level_comment.body) is not None):
                            content["comments"].append(
                                {
                                    "comment_body": top_level_comment.body,
                                    "comment_url": top_level_comment.permalink,
                                    "comment_id": top_level_comment.id,
                                }
                            )

    print_substep("Received subreddit threads Successfully.", style="bold green")

    # New: Clean up the story using AI
    if settings.config["settings"]["storymode"]:
        story_text = content["thread_post"]
        print("Old story content: (before AI)")
        print(story_text)
        content["thread_post"] = clean_story_with_ai(story_text)
        print("New content (after AI):")
        print(content["thread_post"])

    return content

def clean_story_with_ai(story_text: list) -> str:
    api_key = settings.config["ai"]["groq_api_key"]  # Get the API key from the config
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Define the system prompt to guide the model's output
    system_prompt = "Please clean up the following story for clarity without changing any details. The story should sound like a reddit story since it comes from reddit, for example don't do stuff like I'm 28, female, do stuff like I (28F) (age is just an example). Keep details such as age and gender, do not make the story soulless. Optimize for TTS use. The story will be used without any filtering so please do not write anything other than the sanitized story. I am serious, DO NOT, WRITE ANYTHING OTHER than the sanitized story, or it will ruin the whole entire automation."

    # Concatenate the story text into a single string
    story_text_str = "\n".join(story_text)

    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": story_text_str}  # Changed this to a single string
        ],
        "max_tokens": 1000,  # Adjust based on your needs
        "temperature": 0.7,
        "model": "llama-3.1-70b-versatile"
    }

    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=data)
        response.raise_for_status()
        cleaned_story = response.json().get("choices")[0].get("message", {}).get("content", "")
        return cleaned_story.strip()  # Clean up the response
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"Error cleaning story: {e}")

    return "\n".join(story_text)  # Fallback to the original if there's an error
