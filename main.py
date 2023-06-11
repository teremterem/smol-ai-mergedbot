import ast
import asyncio
import os
import traceback
from pprint import pformat

import discord
import promptlayer
import tiktoken
from botmerger import InMemoryBotMerger, SingleTurnContext
from botmerger.ext.discord_integration import attach_bot_to_discord
from dotenv import load_dotenv

from constants import DEFAULT_DIR, DEFAULT_MODEL, DEFAULT_MAX_TOKENS
from utils import clean_dir

load_dotenv()

promptlayer.api_key = os.environ["PROMPTLAYER_API_KEY"]
DISCORD_BOT_SECRET = os.environ["DISCORD_BOT_SECRET"]

discord_client = discord.Client(intents=discord.Intents.default())

openai = promptlayer.openai
# Set up your OpenAI API credentials
openai.api_key = os.environ["OPENAI_API_KEY"]

merger = InMemoryBotMerger()


@merger.create_bot("ResponseGenerator")
async def generate_response(context: SingleTurnContext) -> None:
    # TODO think how to implement `concurrency_limit=5`
    user_prompt = context.request.content["user_prompt"]
    system_prompt = context.request.content.get("system_prompt")
    args = context.request.content.get("args") or []
    model = context.request.content.get("model") or DEFAULT_MODEL

    def reportTokens(prompt):
        encoding = tiktoken.encoding_for_model(model)
        # print number of tokens in light gray, with first 50 characters of prompt in green. if truncated, show that
        # it is truncated
        # TODO send this to the UserProxyBot
        print(
            "\033[37m" + str(len(encoding.encode(prompt))) + " tokens\033[0m" + " in prompt: " + "\033[92m" +
            prompt[:50] + "\033[0m" + ("..." if len(prompt) > 50 else "")
        )

    messages = []
    messages.append({"role": "system", "content": system_prompt})
    reportTokens(system_prompt)
    messages.append({"role": "user", "content": user_prompt})
    reportTokens(user_prompt)
    # Loop through each value in `args` and add it to messages alternating role between "assistant" and "user"
    role = "assistant"
    for value in args:
        messages.append({"role": role, "content": value})
        reportTokens(value)
        role = "user" if role == "assistant" else "assistant"

    params = {
        "model": model,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "temperature": 0,
    }

    # Send the API request
    response = await openai.ChatCompletion.acreate(**params)

    # Get the reply from the API response
    reply = response.choices[0]["message"]["content"]

    await context.yield_response(reply)


# def generate_file(filename, model=DEFAULT_MODEL, filepaths_string=None, shared_dependencies=None, prompt=None):
@merger.create_bot("FileGenerator")
async def generate_file(context: SingleTurnContext) -> None:
    filename = context.request.content["file"]
    model = context.request.content.get("model") or DEFAULT_MODEL
    filepaths_string = context.request.content.get("filepaths_string")
    shared_dependencies = context.request.content.get("shared_dependencies")
    prompt = context.request.content.get("prompt")

    # TODO send this to the UserProxyBot
    print("file", filename)

    # call openai api with this prompt
    filecode_msg = await context.get_another_bot_final_response(
        another_bot=generate_response.bot,
        request={
            "model": model,
            "system_prompt": f"""You are an AI developer who is trying to write a program that will generate code \
for the user based on their intent.

the app is: {prompt}

the files we have decided to generate are: {filepaths_string}

the shared dependencies (like filenames and variable names) we have decided on are: {shared_dependencies}

only write valid code for the given filepath and file type, and return only the code.
do not add any other explanation, only return valid code for that file type.""",
            "user_prompt": f"""We have broken up the program into per-file generation.
Now your job is to generate only the code for the file {filename}.
Make sure to have consistent filenames if you reference other files we are also generating.

Remember that you must obey 3 things:
   - you are generating code for the file {filename}
   - do not stray from the names of the files and the shared dependencies we have decided on
   - MOST IMPORTANT OF ALL - the purpose of our app is {prompt} - every line of code you generate must be valid \
code. Do not include code fences in your response, for example

Bad response:
```javascript
console.log("hello world")
```

Good response:
console.log("hello world")

Begin generating the code now.""",
        },
    )
    await context.yield_response(filecode_msg.message.content)


@merger.create_bot("SmolAI")
async def smol_ai(context: SingleTurnContext) -> None:
    prompt = context.request.content["prompt"]
    directory = context.request.content.get("directory") or DEFAULT_DIR
    model = context.request.content.get("model") or DEFAULT_MODEL
    file = context.request.content.get("file")

    # TODO send this to the UserProxyBot
    print("hi its me, 🐣the smol developer🐣! you said you wanted:")
    # print the prompt in green color
    print("\033[92m" + prompt + "\033[0m")

    # call openai api with this prompt
    filepaths_msg = await context.get_another_bot_final_response(
        another_bot=generate_response.bot,
        request={
            "model": model,
            "system_prompt": """You are an AI developer who is trying to write a program that will generate code \
for the user based on their intent.

When given their intent, create a complete, exhaustive list of filepaths that the user would write to make the \
program.

only list the filepaths you would write, and return them as a python list of strings. 
do not add any other explanation, only return a python list of strings.""",
            "user_prompt": prompt,
        },
    )
    filepaths_string = filepaths_msg.message.content

    # TODO send this to the UserProxyBot
    print(filepaths_string)

    async def call_file_generation_bot(_file: str) -> None:
        file_response = await context.get_another_bot_final_response(
            another_bot=generate_file.bot,
            request={
                "model": model,
                "file": _file,
                "filepaths_string": filepaths_string,
                "shared_dependencies": shared_dependencies,
                "prompt": prompt,
            },
        )
        filecode = file_response.message.content
        write_file(_file, filecode, directory)

    try:
        # parse the result into a python list
        list_actual = ast.literal_eval(filepaths_string)
        await context.yield_response(list_actual, show_typing_indicator=True)

        # if shared_dependencies.md is there, read it in, else set it to None
        shared_dependencies = None
        if os.path.exists("shared_dependencies.md"):
            with open("shared_dependencies.md", "r") as shared_dependencies_file:
                shared_dependencies = shared_dependencies_file.read()

        if file is not None:
            await call_file_generation_bot(file)
        else:
            clean_dir(directory)

            # understand shared dependencies
            shared_dependencies_msg = await context.get_another_bot_final_response(
                another_bot=generate_response.bot,
                request={
                    "model": model,
                    "system_prompt": """You are an AI developer who is trying to write a program that will \
generate code for the user based on their intent.

In response to the user's prompt:

---
the app is: {prompt}
---

the files we have decided to generate are: {filepaths_string}

Now that we have a list of files, we need to understand what dependencies they share.
Please name and briefly describe what is shared between the files we are generating, including exported \
variables, data schemas, id names of every DOM elements that javascript functions will use, message names, and \
function names.
Exclusively focus on the names of the shared dependencies, and do not add any other explanation.""",
                    "user_prompt": prompt,
                },
            )
            shared_dependencies = shared_dependencies_msg.message.content

            # # TODO FeedbackBot
            # async for usr_msg in bot.manager.fulfill("FeedbackBot", await bot.manager.create_originator_message(
            #     channel_type="bot-to-human",
            #     channel_id=str(uuid4()),
            #     originator=bot,
            #     content=shared_dependencies,
            #     custom_fields={
            #         "human_channel_type": request.custom_fields["human_channel_type"],
            #         "human_channel_id": request.custom_fields["human_channel_id"],
            #     },
            # )):
            #     conv_sequence.yield_outgoing(usr_msg)

            # write shared dependencies as a md file inside the generated directory
            write_file("shared_dependencies.md", shared_dependencies, directory)

            await context.yield_response(
                pformat(
                    await asyncio.gather(
                        *[call_file_generation_bot(f) for f in list_actual],
                        return_exceptions=True,
                    )
                ),
                show_typing_indicator=True,
            )
            await context.yield_response("DONE!")
    except ValueError:
        await context.yield_response("Failed to parse result", show_typing_indicator=True)
        await context.yield_response(traceback.format_exc())


def write_file(filename, filecode, directory):
    # Output the filename in blue color
    print("\033[94m" + filename + "\033[0m")
    print(filecode)

    file_path = os.path.join(directory, filename)
    _dir = os.path.dirname(file_path)

    # Check if the filename is actually a directory
    if os.path.isdir(file_path):
        print(f"Error: {filename} is a directory, not a file.")
        return

    os.makedirs(_dir, exist_ok=True)

    # Open the file in write mode
    with open(file_path, "w") as file:
        # Write content to the file
        file.write(filecode)


@merger.create_bot("MainBot")
async def main(context: SingleTurnContext) -> None:
    prompt = context.request.content
    directory = DEFAULT_DIR
    file = None

    # read file from prompt if it ends in a .md filetype
    if prompt.endswith(".md"):
        with open(prompt, "r") as promptfile:
            prompt = promptfile.read()

    await context.yield_from(
        await context.trigger_another_bot(
            another_bot=smol_ai.bot,
            request={
                "model": "gpt-4",
                "directory": directory,
                "file": file,
                "prompt": prompt,
            },
        )
    )


# # TODO ?
# two_way_bot_wrapper = TwoWayBotWrapper(
#     manager=bot_manager,
#     this_bot_handle="TwoWayBot",
#     target_bot_handle=main.bot.handle,
#     feedback_bot_handle="FeedbackBot",
# )


@discord_client.event
async def on_ready() -> None:
    """Called when the client is done preparing the data received from Discord."""
    print("Logged in as", discord_client.user)
    print()


if __name__ == "__main__":
    attach_bot_to_discord(main.bot, discord_client)
    discord_client.run(DISCORD_BOT_SECRET)
