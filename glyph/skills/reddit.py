from datetime import datetime
from os import environ

import discord
import praw
import prawcore
from praw import exceptions

from .commander import register


@register("reddit")
async def send_image(bot, message, ai, config):
    r = praw.Reddit(client_id=environ.get("REDDIT_CLIENT_ID"),
                    client_secret=environ.get("REDDIT_SECRET"),
                    user_agent=environ.get("REDDIT_USER_AGENT"))
    multireddit = ai.get_parameter("multireddit")
    if multireddit is None:
        await bot.safe_send_message(message.channel, "I think you wanted an image from Reddit, "
                                                          "but I'm not sure of what. Sorry.")
        return
    try:
        nsfw_subreddit = [s for s in multireddit.split("+") if r.subreddit(s).over18]
        try:
            nswf_channel = "nsfw" in message.channel.name
        except TypeError:
            nswf_channel = False
        if nsfw_subreddit and not nswf_channel:
            await self.bot.safe_send_message(message.channel, "You must be in a NSFW channel "
                                                              "to view images from `{}`".format(multireddit))
            return
        for i in range(1, 20):  # Get an image that can be embedded
            try:
                submission = r.subreddit(multireddit).random()
            except TypeError:
                continue
            if submission.over_18 and not nswf_channel:
                continue
            elif any(extension in submission.url for extension in [".png", ".jpg", ".jpeg", ".gif"]) \
                    and submission.score > 10:
                embed = discord.Embed(title=submission.title, url=submission.shortlink, timestamp=datetime.utcnow())
                embed.set_image(url=submission.url)
                suggestion = r.subreddit("popular").random().subreddit.display_name
                embed.set_footer(text="r/{} | Try asking \"r/{}\"".format(submission.subreddit, suggestion))
                await bot.safe_send_message(message.channel, embed=embed, deletewith=message)
                break
        else:
            await bot.safe_send_message(message.channel, "Sorry, I took too long to try to find an image.")
    except (prawcore.exceptions.NotFound, prawcore.exceptions.Redirect):
        await bot.safe_send_message(message.channel,
                                         "You provided an unknown or invalid subreddit `{}`.".format(multireddit))
    except prawcore.exceptions.Forbidden:
        await bot.safe_send_message(message.channel, "Sorry, but `{}` is a private community and so "
                                                          "I can not grab a photo from there.".format(multireddit))
    except (praw.exceptions.ClientException, praw.exceptions.APIException):
        await bot.safe_send_message(message.channel, "Sorry, I had an issue communicating with Reddit.")
