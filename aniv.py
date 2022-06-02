import signal
import os
import ujson
import random
import re
import asyncio
import time
import shutil
import datetime
import aiofiles
import copy
from twitchio.ext import commands
from auth import Auth
from concurrent.futures import ThreadPoolExecutor
from googletrans import Translator, LANGUAGES

class Utils():
    def load_json_file(filename, key=None):
        with open(filename, 'r') as f:
            res = ujson.load(f)
            if key:
                res = res[key]
            return res
            
    def save_json_file(srcfile, new_contents, backup=True):
        try:
            if backup:
                shutil.copy2(srcfile, 'data/backups')
            with open(srcfile, 'w', encoding='utf-8') as f:
                ujson.dump(new_contents, f, indent=4)
        except Exception as e:
            print("Exception occured during save_json_file:",srcfile,"- Exception:",e)
            return False
            
        return True
        
    def log(*msg):
        msg = ' '.join(map(str, msg))
        print(msg)
        now = datetime.datetime.now()
        timestamp = now.strftime("%m/%d/%Y %H:%M:%S")
        fmsg = f'[{timestamp}] {msg}'
        with open('log.txt', 'a', encoding='utf-8') as f:
            f.write(fmsg + '\n')

class Markov():
    def __init__(self):
        self.__dict = dict()
        self.__order = 10
        self.__OUTPUT_MAX = 200
        self.__MAX_GEN_ATTEMPTS = 20
        self.__ignore_list = Utils.load_json_file('data/user_ignore_list.json', 'ignore_list')
        self.__channel_ignore_list = Utils.load_json_file('data/channel_ignore_list.json', 'ignore_list')
        self.__filter_list = Utils.load_json_file('data/filter.json', 'filter_list')

    def is_safe_to_learn(self, channel, name, msg):
        if channel.lower() in self.__channel_ignore_list:
            return False
        if name.lower() in self.__ignore_list:
            return False
        if any([(filter.lower() in msg.lower()) for filter in self.__filter_list]):
            return False
            
        return True

    def learn_from_buffer(self, data):
        for i in range(len(data) - self.__order):
            key = data[i:i+self.__order]
            char = data[i+self.__order]
                
            if not key in self.__dict:
                self.__dict[key] = dict()
            if not char in self.__dict[key]:
                self.__dict[key][char] = 0
            self.__dict[key][char] += 1
        
        return data[-self.__order:]

    async def save_buffers(self):
        async with aiofiles.open('markov_dict.txt', 'w') as f:
            await f.write(ujson.dumps({'dict': self.__dict}))
            await f.flush()

    def load(self):
        with open('markov_dict.txt', 'r') as f:
            r = ujson.loads(f.read())
            self.__dict = r['dict']
            
    def hasResponse(self, msg):
        return msg[-self.__order:] in self.__dict
        
    def getKey(self, msg):
        return msg[-self.__order:].replace("\n", "\\n")
        
    def trimDataStream(self, msg):
        return msg[-self.__order:]
            
    def gen(self, inp):
        attemptCount = 0
        inp = inp[-self.__order:]
        
        if not inp in self.__dict:
            return None
            
        while attemptCount < self.__MAX_GEN_ATTEMPTS:
            output = ""
            if len(inp) > 0:
                output = '' if inp[-1] == '\n' else inp
                
            for i in range(self.__OUTPUT_MAX):
                #print('DEBUG:',inp,'-',self.__dict[inp])
                mapping = self.__dict[inp]
                char = random.choices(list(mapping.keys()), list(mapping.values()))[0]
                output += char
                if char == '\n':
                    break
                inp = inp[1:] + char
            output = output.rstrip()
            if any([(filter.lower() in output.lower()) for filter in self.__filter_list]):
                attemptCount += 1
            else:
                break
                
        
        return output
        
class UserSettings():
    def __init__(self, settings_file):
        self.__MIN_MESSAGES_PER_POST = 14
        self.__MAX_MESSAGES_PER_POST = 200
        self.__default_post_settings = {
                "post_min": 30,
                "post_max": 70,
                "translate": []
            }
        self.__settings_file = settings_file
        self.__post_settings = Utils.load_json_file(settings_file)
        self.__translator = Translator()
    
    def clamp_post_rate(self, rate):
        return max(self.__MIN_MESSAGES_PER_POST, min(rate, self.__MAX_MESSAGES_PER_POST))

    def get_post_settings(self, channel):
        if channel in self.__post_settings:
            return self.__post_settings[channel]
        return self.__post_settings['default']
        
    def get_or_create_post_settings(self, channel):
        if not channel in self.__post_settings:
            self.__post_settings[channel] = copy.deepcopy(self.__default_post_settings)
        return self.__post_settings[channel]

    def get_post_min(self, channel):
        post_settings = self.get_post_settings(channel)
        return post_settings['post_min']

    def get_post_max(self, channel):
        post_settings = self.get_post_settings(channel)
        return post_settings['post_max']
        
    def get_translation(self, channel):
        post_settings = self.get_post_settings(channel)
        return post_settings['translate']
        
    def set_post_range(self, channel, min, max):
        post_settings = self.get_or_create_post_settings(channel)
        post_settings["post_min"] = min
        post_settings["post_max"] = max
        
    def set_translation(self, channel, languages):
        post_settings = self.get_or_create_post_settings(channel)
        post_settings["translate"] = languages
            
        return None
        
    def get_translate_lang(self, translations):
        if isinstance(translations, str):
            return translations
        elif isinstance(translations, list):
            if len(translations) > 0:
                return random.choice(translations)
        
    def translate_message(self, channel, msg):
        if channel in self.__post_settings:
            if 'translate' in self.__post_settings[channel]:
                if not re.match("^!\w+", msg):
                    translate_lang = self.get_translate_lang(self.__post_settings[channel]['translate'])
                    if translate_lang:
                        d = self.__translator.detect(msg)
                        if d.lang != translate_lang:
                            msg = self.__translator.translate(msg, translate_lang).text
        return msg
        
    def save(self):
        return Utils.save_json_file(self.__settings_file, self.__post_settings)
        
class Bot(commands.Bot):
    
    def __init__(self, in_markov):   
        self.__MAX_CHANNEL_JOIN_LIMIT = 19
        self.auth = Auth('auth.json')
        
        self.__user_settings = UserSettings('data/channel_settings.json')
        
        loaded_channels = Utils.load_json_file('data/channels.json', 'channels')
        self.__channels = loaded_channels[:self.__MAX_CHANNEL_JOIN_LIMIT]
        self.__channel_join_queue = loaded_channels[self.__MAX_CHANNEL_JOIN_LIMIT:]
        
        self.__channels_to_learn_from = dict()
        
        to_join = loaded_channels[:self.__MAX_CHANNEL_JOIN_LIMIT]
        super().__init__(
            token=self.auth.get_irc_token(),
            nick=self.auth.get_user(),
            prefix='!',
            initial_channels=to_join
        )
        
        Utils.log(f"Joined {len(to_join)} of {len(loaded_channels)} loaded channels:",", ".join(to_join))
        
        self.__last_join_time = datetime.datetime.now().timestamp()
        self.__last_dict_save_time = datetime.datetime.now().timestamp()
        self.__new_channel_added = False
        self.__longest_username = self.get_longest_username()
        
        self.msg_data = dict()
        self.markov = in_markov
        
        self.__percent_chance_to_tag_user = 8
        self.__percent_chance_to_respond_to_tag = 1

    def get_longest_username(self):
        return max(len(x) for x in self.__channels+self.__channel_join_queue)

    async def event_ready(self):
        print('Connected!')

    async def event_raw_data(self, data):
        #print(data)
        pass
        
    async def event_command_error(self, ctx, error):
        pass

    async def send_message(self, channel, message):
        channel = self.get_channel(channel)
        msg = self.markov.gen(message)
        if msg:
            msg = self.__user_settings.translate_message(channel.name.lower(), msg)
            Utils.log("Sending:", msg)
            await channel.send(msg)

    async def handle_chat_message(self, message, channel):
        if channel not in self.msg_data:
            self.msg_data[channel] = {
                'msg_count': 0,
                'msg_post_rate': random.randint(10, 18),
                'last_user': '',
                'reply_msg': '',
                'datastream': '',
                'msgstream': '',
            }
            Utils.log(channel.ljust(self.__longest_username), ':', 'posting in',self.msg_data[channel]['msg_post_rate'])
            
        channel_data = self.msg_data[channel]
        
        if f'@{self.auth.get_user().lower()}' in message.content.lower():
            if random.randint(0,99) < self.__percent_chance_to_respond_to_tag:
                msg = re.sub(f'\\s?@{self.auth.get_user().lower()}\\s?', '', message.content.lower())
                new_msg = self.markov.gen(msg + '\n')
                if new_msg:
                    new_msg = f"@{message.author.display_name} {new_msg}"
                    Utils.log(f"{channel.ljust(self.__longest_username)}: ({channel_data['msg_post_rate']})[{markov.getKey(msg).rstrip()}][{message.author.display_name}] {new_msg}")
                    time.sleep(random.randint(3, 6))
                    await message.channel.send(new_msg)
                    return
        
        channel_data['msg_count'] += 1
        channel_data['msgstream'] = self.markov.trimDataStream(channel_data['msgstream'] + message.content + "\n")
        if self.markov.is_safe_to_learn(channel, message.author.name, message.content):
            channel_data['datastream'] = channel_data['datastream'] + message.content + "\n"
            self.__channels_to_learn_from[channel] = True
            
        if self.markov.hasResponse(channel_data['msgstream']):
            channel_data['reply_msg'] = self.markov.trimDataStream(channel_data['msgstream'])
            channel_data['last_user'] = message.author.display_name
        
        if channel_data['msg_count'] >= channel_data['msg_post_rate']:
            msg = self.markov.gen(channel_data['reply_msg'])
            if msg:
                channel_data['msg_count'] = 0
                channel_data['msg_post_rate'] = random.randint(self.__user_settings.get_post_min(channel), self.__user_settings.get_post_max(channel))
                if random.randint(1, 100) <= self.__percent_chance_to_tag_user:
                    msg = f"@{message.author.display_name} {msg}"
                Utils.log(f"{channel.ljust(self.__longest_username)}: ({channel_data['msg_post_rate']})[{markov.getKey(channel_data['reply_msg']).rstrip()}] {msg}")
                
                msg = self.__user_settings.translate_message(channel, msg)
                time.sleep(random.randint(3, 8))
                await message.channel.send(msg)

    async def join_channel(self, channels):
        new_channels = []
        for channel in channels:
            if not channel in self.__channels:
                self.__channels.append(channel)
                new_channels.append(channel)

        await self.join_channels(channels)
        Utils.log("*** Joining channels:",', '.join(channels))
        if self.__new_channel_added:
            if Utils.save_json_file('data/channels.json', {"channels": self.__channels}):
                self.__new_channel_added = False
                return True
            print("Error saving channels json")
            return False
            
        return True

    async def handle_summon(self, message, args):
        author = message.author.name.lower()
        if not author in self.__channels:
            self.__channel_join_queue.append(author)
            self.__new_channel_added = True
            self.__longest_username = self.get_longest_username()
            await message.channel.send(f"Joining your channel now, {message.author.display_name}!")
    
    async def handle_unsummon(self, message, args):
        author = message.author.name.lower()
        if author in self.__channels:
            self.__channels.remove(author)
            self.__longest_username = self.get_longest_username()
            if Utils.save_json_file('data/channels.json', {"channels": self.__channels}):
                Utils.log("*** Left channel",message.author.display_name)
                await message.channel.send(f"Alright, I'm out of there, {message.author.display_name}!")
                await self._connection.send(f"PART #{author}\r\n")
    
    async def handle_msgrate(self, message, args):
        author = message.author.name.lower()
        
        min_rate = self.__user_settings.get_post_min(author)
        max_rate = self.__user_settings.get_post_max(author)
        
        msg_response = f"@{message.author.display_name}, I will talk every {min_rate} to {max_rate} messages in your chat. To change this, use `!msgrate <min> <max>`. For example, `!msgrate 20 40` to chat every 20 to 40 messages."
        
        if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
            min_rate = self.__user_settings.clamp_post_rate(int(args[0]))
            max_rate = self.__user_settings.clamp_post_rate(int(args[1]))
            self.__user_settings.set_post_range(author, min_rate, max_rate)
            if self.__user_settings.save():
                Utils.log("*** Updated min/max for channel",message.author.display_name,"to",min_rate,max_rate)
                msg_response = f"Min and max post settings updated. Thanks @{message.author.display_name}!"
        
        await message.channel.send(msg_response)
        
    async def handle_translate(self, message, args):
        author = message.author.name.lower()
        
        translate = self.__user_settings.get_translation(author)
        
        msg_response = f"@{message.author.display_name}, I am not currently translating any messages for you. To change this, use `!translate <lang1> <lang2> ... <langN>`, or `!translate none` to clear. For example, `!translate es en` to translate half messages into spanish and half into english."
        
        if len(args) == 1 and args[0].lower() == 'none':
            self.__user_settings.set_translation(author, [])
            if self.__user_settings.save():
                Utils.log("*** Updated translation for channel",message.author.display_name,"to",args)
                msg_response = f"Translation cleared. Thanks @{message.author.display_name}!"
        elif len(args) > 0:
            for lang in args:
                if not lang in LANGUAGES:
                    msg_response = f"@{message.author.display_name}, I don't know the language `{lang}`."
                    await message.channel.send(msg_response)
                    return
            self.__user_settings.set_translation(author, args)
            if self.__user_settings.save():
                Utils.log("*** Updated translation for channel",message.author.display_name,"to",args)
                msg_response = f"Translation settings updated. Thanks @{message.author.display_name}!"
        elif not translate == []:
            msg_response = f"@{message.author.display_name}, I'm currently translating into these languages for you: {', '.join(translate)}. To change this, use `!translate <lang1> <lang2> ... <langN>`, or `!translate none` to clear. For example, `!translate es en` to translate half messages into spanish and half into english."
            
        await message.channel.send(msg_response)

    async def handle_channel_command(self, message, command_and_args):
        command = command_and_args[0][1:]
        
        commands = {
            'summon': self.handle_summon,
            'unsummon': self.handle_unsummon,
            'msgrate': self.handle_msgrate,
            'translate': self.handle_translate,
        }
        if command in commands:
            await commands[command](message, command_and_args[1:])

    async def handle_self_chat(self, message, channel):
        if f'@{self.auth.get_user().lower()}' in message.content.lower():
            msg = re.sub(f'\\s?@{self.auth.get_user().lower()}\\s?', '', message.content.lower())
            msg = self.markov.gen(msg + '\n')
            if msg:
                msg = f"@{message.author.display_name} {msg}"
                await message.channel.send(msg)
            return
        
        msg = message.content.lower()
        if len(msg) > 0 and msg[0] == '!':
            command = msg.split()
            await self.handle_channel_command(message, command)
            # add to list, etc

    async def event_message(self, message):
        if message.author and message.channel:
            if message.author.name.lower() in ['funtoon', 'cynanbot', self.auth.get_user().lower()]:
                return
                
            channel = message.channel.name.lower()
            
            if channel == self.auth.get_user().lower():
                await self.handle_self_chat(message, channel)
            else:
                await self.handle_chat_message(message, channel)
                
    async def process_channel_joins(self):
        while True:
            ts = datetime.datetime.now().timestamp()
            if ts - self.__last_join_time > 12:
                if len(self.__channel_join_queue) > 0:
                    self.__last_join_time = ts
                    to_join = self.__channel_join_queue[:self.__MAX_CHANNEL_JOIN_LIMIT]
                    self.__channel_join_queue = self.__channel_join_queue[self.__MAX_CHANNEL_JOIN_LIMIT:]
                    await self.join_channel(to_join)
            await asyncio.sleep(1)
            
    async def learn_new_data(self):
        changes_made = False
        while True:
            if len(self.__channels_to_learn_from) > 0:
                for channel in self.__channels_to_learn_from:
                    self.markov.learn_from_buffer(self.msg_data[channel]['datastream'])
                    self.msg_data[channel]['datastream'] = self.markov.trimDataStream(self.msg_data[channel]['datastream'])
                
                changes_made = True
                self.__channels_to_learn_from = dict()
                
            ts = datetime.datetime.now().timestamp()
            if (ts - self.__last_dict_save_time > 300) and changes_made:
                await self.markov.save_buffers()
                self.__last_dict_save_time = datetime.datetime.now().timestamp()
                changes_made = False
                
            await asyncio.sleep(1)
            
async def ainput(prompt: str = ''):
    with ThreadPoolExecutor(1, 'ainput') as executor:
        return (await asyncio.get_event_loop().run_in_executor(executor, input, prompt))
        
async def input_thread(bot):
    while True:
        inp = await ainput("(markov) >> ")
        if len(inp) > 0 and inp[0] == '/':
            cmd, args = inp[1::].split(' ', 1)
            if cmd.lower() == "join":
                await bot.join_channel(args)
        else:
            chan, res = inp.split(' ', 1)
            await bot.send_message(chan, res + '\n')

if __name__ == '__main__':
    # make Ctrl-C actually kill the process
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    markov = Markov()
    
    while True:
        inp = input("(markov) >> ")
            
        if len(inp) > 0 and inp[0] == '/':
            inp = inp[1::]
            if inp.lower() == "run":
                break
            elif inp.lower() == "load":
                markov.load()
            else:
                print("Unknown command")
        else:
            print(markov.gen(inp + '\n'))
            
    markov.load()
    bot = Bot(markov)
    loop = asyncio.get_event_loop()
    loop.create_task(input_thread(bot))
    loop.create_task(bot.process_channel_joins())
    loop.create_task(bot.learn_new_data())
    bot.run()
    print("Done")