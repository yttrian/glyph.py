import asyncio
import logging
import re
from json.decoder import JSONDecodeError
from os import environ

import discord
import requests

from . import apiai
from . import auditing
from . import fa
from . import picarto
from . import skills
from .serverconfig import ConfigDatabase

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
log.addHandler(ch)


class GlyphBot(discord.Client):

    def __init__(self):
        self.auditor = auditing.Auditor(self)
        self.apiai = apiai.AIProcessor(client_access_token=environ.get("APIAI_TOKEN"))
        self.configdb = ConfigDatabase(environ.get("DATABASE_URL"))
        self.removable_messages = []
        self.deletewith_messages = {}
        self.total_members = lambda: sum(1 for i in self.get_all_members())
        self.total_servers = lambda: len(self.servers)
        self.ready = False
        self.skill_commander = skills.SkillCommander(self)
        super().__init__()

    async def update_server_count(self):
        count = len(self.servers)
        # Discord Bot List
        url = "https://discordbots.org/api/bots/{}/stats".format(self.user.id)
        header = {"Content-Type": "application/json", "Authorization": environ.get("DISCORDBOTLIST_TOKEN")}
        data = {"server_count": count}
        req = requests.post(url, json=data, headers=header)
        if req.status_code == 200:
            log.info("Updated Discord Bot List count with {} servers!".format(count))
        else:
            log.warning("Failed to update Discord Bot List server count with error code {}!".format(req.status_code))
        # Discord Bots
        url = "https://bots.discord.pw/api/bots/{}/stats".format(self.user.id)
        header = {"Content-Type": "application/json", "Authorization": environ.get("DISCORDBOTS_TOKEN")}
        data = {"server_count": count}
        req = requests.post(url, json=data, headers=header)
        if req.status_code == 200:
            log.info("Updated Discord Bots count with {} servers!".format(count))
        else:
            log.warning("Failed to update Discord Bots server count with error code {}!".format(req.status_code))

    async def safe_send_typing(self, destination):
        if destination is None:
            log.error("Send typing needs a destination!")
            return None
        try:
            await self.send_typing(destination)
        except discord.Forbidden:
            log.warning("{} - {}: Cannot send typing, no permission?".format(destination.server, destination.name))
        except discord.NotFound:
            log.warning("{} - {}: Cannot send typing, invalid channel?".format(destination.server, destination.name))
        except discord.HTTPException:
            log.warning("{} - {}: Cannot send typing, failed.".format(destination.server, destination.name))

    async def safe_send_message(self, destination, content=None, *, embed=None, expire_time=0, removable=False,
                                deletewith=None):
        if content is None and embed is None:
            log.error("A message needs to have content!")
            return None
        elif embed is not None and removable and not expire_time:
            if embed.footer.text is not discord.Embed.Empty:
                embed.set_footer(text="React \u274C to remove | {}".format(embed.footer.text))
            else:
                embed.set_footer(text="React \u274C to remove")
        msg = None
        try:
            msg = await self.send_message(destination, content, embed=embed)

            if msg and deletewith:
                self.deletewith_messages.update({deletewith.id: msg})
            if msg and expire_time:
                await asyncio.sleep(expire_time)
                await self.delete_message(msg)
            elif msg and removable:
                self.removable_messages.append(msg.id)
        except discord.Forbidden:
            log.warning("{} - {}: Cannot send message, no permission?".format(destination.server, destination.name))
        except discord.NotFound:
            log.warning("{} - {}: Cannot send message, invalid channel?".format(destination.server, destination.name))
        except discord.HTTPException:
            log.warning("{} - {}: Cannot send message, failed.".format(destination.server, destination.name))

        return msg

    async def safe_edit_message(self, message, new=None, *,
                                embed=None, expire_time=0, clear_reactions=False, removable=False):
        if message is None:
            return
        elif embed is not None and removable and not expire_time:
            if embed.footer.text is not discord.Embed.Empty:
                embed.set_footer(text="React \u274C to remove | {}".format(embed.footer.text))
            else:
                embed.set_footer(text="React \u274C to remove")
        msg = None
        if clear_reactions:
            await self.safe_clear_reactions(message)
        try:
            msg = await self.edit_message(message, new, embed=embed)

            if msg and expire_time:
                await asyncio.sleep(expire_time)
                await self.delete_message(msg)
            elif msg and removable:
                self.removable_messages.append(msg.id)
        except discord.NotFound:
            log.warning("Cannot edit message \"{}\", message not found".format(message.clean_content))
        except discord.HTTPException:
            log.warning("Cannot edit message \"{}\", failed.".format(message.clean_content))

        return msg

    async def safe_delete_message(self, message):
        try:
            return await self.delete_message(message)
        except discord.Forbidden:
            log.warning("Cannot delete message \"{}\", no permission?".format(message.clean_content))
        except discord.NotFound:
            log.warning("Cannot delete message \"{}\", invalid channel?".format(message.clean_content))
        except discord.HTTPException:
            log.warning("Cannot delete message \"{}\", failed.".format(message.clean_content))

    async def safe_purge_from(self, channel, *, limit=100, check=None, before=None, after=None, around=None):
        purges = None
        try:
            purges = await self.purge_from(channel, limit=limit, check=check, before=before, after=after, around=around)
        except discord.Forbidden:
            log.warning("{} - {}: Cannot purge messages, no permission?".format(channel.server, channel.name))
        except discord.NotFound:
            log.warning("{} - {}: Cannot purge messages, invalid channel?".format(channel.server, channel.name))
        return purges

    async def safe_add_reaction(self, message, emoji):
        reaction = None
        channel = message.channel
        try:
            reaction = await self.add_reaction(message, emoji)
        except discord.Forbidden:
            log.warning("{} - {}: Cannot add reaction, no permission?".format(channel.server, channel.name))
        except discord.NotFound:
            log.warning("{} - {}: Cannot add reaction, invalid message or emoji?".format(channel.server, channel.name))
        return reaction

    async def safe_clear_reactions(self, message):
        channel = message.channel
        try:
            await self.clear_reactions(message)
        except discord.Forbidden:
            log.warning("{} - {}: Cannot clear reactions, no permission?".format(channel.server, channel.name))

    async def safe_kick(self, member):
        kick = None
        try:
            kick = await self.kick(member)
        except discord.Forbidden:
            log.warning("{}: Cannot kick member, no permission?".format(member.server))
        except discord.HTTPException:
            log.warning("{}: Cannot kick member, kicking failed?".format(member.server))
        return kick

    async def safe_add_roles(self, member, *roles):
        try:
            await self.add_roles(member, *roles)
            return True
        except discord.Forbidden:
            log.warning("{}: Cannot add roles, no permission?".format(member.server))
            return False

    async def safe_remove_roles(self, member, *roles):
        try:
            await self.remove_roles(member, *roles)
            return True
        except discord.Forbidden:
            log.warning("{}: Cannot remove roles, no permission?".format(member.server))
            return False

    async def on_ready(self):
        log.info("Logged in as {} ({})".format(self.user.name, self.user.id))
        await self.change_presence(game=discord.Game(name="Armax Arsenal Arena"))
        farm_servers = []
        for server in list(self.servers):
            total_members = len(server.members)
            total_bots = len(list(filter(lambda member: member.bot, server.members)))
            total_humans = total_members - total_bots
            percentage_bots = round(total_bots/total_members*100, 2)
            if percentage_bots > 80 and total_members > 15:
                farm_servers.append(server)
                log.info("{}: Left server! Was {}% likely to be a bot farm with {} members, "
                         "{} humans and {} bots!".format(
                            server.name, percentage_bots, total_members, total_humans, total_bots))
                await asyncio.sleep(2)  # Wait because of rate limiting
                await self.leave_server(server)
        log.info("Left {} bot farm server(s).".format(len(farm_servers)))
        self.configdb.load_all()
        log.info("Loaded {} configurations from the database.".format(len(self.configdb.configs)))
        await self.update_server_count()
        log.info("Connected to {} server(s) with {} members.".format(self.total_servers(), self.total_members()))
        self.ready = True

    async def on_message(self, message):
        if not self.ready:
            return
        # Don't talk to yourself
        if message.author == self.user or message.author.bot:
            return
        server = message.server
        config = self.configdb.get(server)
        # Check for spoilery words
        if config["spoilers"]["keywords"]:
            spoilers_channel = config["spoilers"]["safe_channel"]
            spoilers_keywords = set(map(lambda x: x.lower(), config["spoilers"]["keywords"]))
            split_message = set(map(str.lower, re.findall(r"[\w']+", message.clean_content)))
            if spoilers_keywords.intersection(split_message) and not (message.channel.name == spoilers_channel):
                await self.safe_add_reaction(message, "\u26A0")  # React with a warning emoji
        # FA QuickView
        r = fa.Submission.regex
        if r.search(message.clean_content) and config["quickview"]["fa"]["enabled"]:
            links = r.findall(message.clean_content)
            for link in links:
                link_type = link[4]
                link_id = link[5]
                if link_type == "view":
                    try:
                        submission = fa.Submission(id=link_id)
                        embed = submission.get_embed(thumbnail=config["quickview"]["fa"]["thumbnail"])
                        await self.safe_send_message(message.channel, embed=embed, deletewith=message)
                    except ValueError:
                        pass
            return
        # Picarto QuickView
        r = picarto.Channel.regex
        if r.search(message.clean_content) and config["quickview"]["picarto"]["enabled"]:
            links = r.findall(message.clean_content)
            for link in links:
                link_name = link[4]
                try:
                    channel = picarto.Channel(name=link_name)
                    embed = channel.get_embed()
                    await self.safe_send_message(message.channel, embed=embed, deletewith=message)
                except ValueError:
                    pass
            return
        # Check if the message should be replied to
        if self.user in message.mentions or message.channel.is_private:
            # Get the member of the bot so the mention can be removed from the message
            try:
                member = discord.utils.get(message.server.members, id=self.user.id)
                if member is None:
                    member = self.user
            except AttributeError:
                member = self.user
            # Check it the mention is at the beginning of the message and don't reply if not
            if not message.clean_content.startswith("@{}".format(member.display_name)) and not message.channel.is_private:
                return
            # Start by typing to indicate processing a successful message
            await self.safe_send_typing(message.channel)
            # Remove the mention from the message so it can be processed right
            clean_message = re.sub("@{}".format(member.display_name), "", message.clean_content).strip()
            if not clean_message:  # If there's no message
                await self.safe_send_message(message.channel, "You have to say something.")
                return
            # Remove self from the list of mentions in the message
            clean_mentions = message.mentions
            try:
                clean_mentions.remove(member)
            except ValueError:
                pass
            # Ask api.ai how to handle the message
            try:
                ai = self.apiai.query(clean_message, message.author.id)
            except JSONDecodeError:  # api.ai is down
                await self.safe_send_message(message.channel, "Sorry, it appears api.ai is currently unavailable.\n"
                                                              "Please try again later.")
                return
            # Do the action given by api.ai
            await self.skill_commander.process(message, ai, config)

    def get_clean_mentions(self, message):
        # Get the member of the bot so the mention can be removed from the message
        try:
            member = discord.utils.get(message.server.members, id=self.user.id)
            if member is None:
                member = self.user
        except AttributeError:
            member = self.user
            # Remove self from the list of mentions in the message
        clean_mentions = message.mentions
        try:
            clean_mentions.remove(member)
        except ValueError:
            pass
        return clean_mentions

    async def on_member_join(self, member):
        if not self.ready:
            return
        server = member.server
        config = self.configdb.get(server)
        if config["auditing"]["joins"]:
            await self.auditor.audit(server, auditing.MEMBER_JOIN, self.auditor.get_user_info(member), user=member)

    async def on_member_remove(self, member):
        if not self.ready:
            return
        server = member.server
        config = self.configdb.get(server)
        if config["auditing"]["leaves"]:
            await self.auditor.audit(server, auditing.MEMBER_LEAVE, self.auditor.get_user_info(member), user=member)

    async def on_reaction_add(self, reaction, user):
        if not self.ready:
            return
        server = reaction.message.server
        config = self.configdb.get(server)
        message = reaction.message
        if config["auditing"]["reactions"]:
            await self.auditor.audit(server, auditing.REACTION_ADD,
                                     "{} added reaction {} to {}".format(user.mention,
                                                                         reaction.emoji,
                                                                         reaction.message.content),
                                     user=user)
        if message.id in self.removable_messages and reaction.emoji == "\u274C":
            embed = discord.Embed(description="<:xmark:344316007164149770> Removed!", color=0xFF0000)
            await self.safe_edit_message(message, embed=embed, expire_time=5, clear_reactions=True)
            self.removable_messages.remove(message.id)

    async def on_reaction_remove(self, reaction, user):
        if not self.ready:
            return
        server = reaction.message.server
        config = self.configdb.get(server)
        if config["auditing"]["reactions"]:
            await self.auditor.audit(server, auditing.REACTION_REMOVE,
                                     "{} removed reaction {} from {}".format(user.mention,
                                                                             reaction.emoji, reaction.message.content),
                                     user=user)

    async def on_message_delete(self, message):
        if not self.ready:
            return
        if message.id in self.deletewith_messages:
            embed = discord.Embed(description="<:xmark:344316007164149770> Removed!", color=0xFF0000)
            msg = self.deletewith_messages.get(message.id)
            await self.safe_edit_message(msg, embed=embed, expire_time=5, clear_reactions=True)
            self.deletewith_messages.pop(message.id)

    async def on_server_join(self, server):
        if not self.ready:
            return
        log.info("{}: Added to server.".format(server))
        await self.update_server_count()

    async def on_server_remove(self, server):
        if not self.ready:
            return
        self.configdb.delete(server.id)
        log.info("{}: Removed from server.".format(server))
        await self.update_server_count()


if __name__ == '__main__':
    bot = GlyphBot()
    bot.run(environ.get("DISCORD_TOKEN"))
