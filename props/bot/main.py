#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
props bot
'''

import os
import re
import sys

from quart import abort, Quart, jsonify, request, Response
from attrdict import AttrDict
from slackclient import SlackClient

from utils.fmt import dbg
from config import CFG

app = Quart(__name__)

slack = SlackClient(CFG.SLACK_BOT_USER_OAUTH_ACCESS_TOKEN)

CONTRIBUTE_JSON = open('contribute.json').read()

PROPS = {}

### incoming webhooks
### https://hooks.slack.com/services/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

parse_regex = re.compile('(?P<target>[A-Za-z0-9_-]+)(:(?P<prop>[A-Za-z0-9_-]+))?(?P<operator>\+\+|--|\+=|-=)?(?P<operand>[0-9])?')

def augment(operator, operand):
    value = int(operand) if operand else 1
    return -1 * value if operator.startswith('-') else value

def parse(text):
    match = parse_regex.search(text)
    if match:
        d = match.groupdict()
        return d['target'], d['prop'], d['operator'], d['operand']
    return [None] * 4

def is_request_valid(token, team_id):
    return token == SLACK_VERIFICATION_TOKEN and team_id == CFG.SLACK_TEAM_ID

class EventTextError(Exception):
    def __init__(self, json):
        msg = f'event.text error; json = {json}'
        super(EventTextError, self).__init__(msg)

class EventChannelError(Exception):
    def __init__(self, json):
        msg = f'event.channel error; json = {json}'
        super(EventChannelError, self).__init__(msg)

class ChannelsListError(Exception):
    def __init__(self, json):
        msg = f'channels.list error; json = {json}'
        super(ChannelsListError, self).__init__(msg)

class ChannelsInfoError(Exception):
    def __init__(self, json):
        msg = f'channels.info error; json = {json}'
        super(ChannelsInfoError, self).__init__(msg)

class MembersListError(Exception):
    def __init__(self, json):
        msg = f'users.list error; json = {json}'
        super(MembersListError, self).__init__(msg)

class PropsBot(object):

    props = {}

    operators = {
        '++': lambda x, y: x + 1,
        '--': lambda x, y: x - 1,
        '+=': lambda x, y: x + int(y),
        '-=': lambda x, y: x - int(y),
    }

    def __init__(self, event):
        self.event = event

    @property
    def text(self):
        if 'text' in self.event:
            return self.event.text
        raise EventTextError(self.event)

    @property
    def channel(self):
        if 'channel' in self.event:
            return self.event.channel
        raise EventChannelError(self.event)

    @property
    def channels(self):
        json = slack.api_call('channels.list')
        if 'channels' in json:
            return [AttrDict(channel) for channel in json['channels']]
        raise ChannelsListError(json)

    @property
    def channels_info(self):
        json = slack.api_call('channels.info', channel=self.channel)
        if 'channel' in json:
            return AttrDict(json['channel'])
        raise ChannelsInfoError(json)

    @property
    def members(self):
        json = slack.api_call('users.list')
        if 'members' in json:
            return [AttrDict(member) for member in json['members']]
        raise MemebersListError(json)

    #members = [user for user in users if user.id in channel_info.members]
    @property
    def members_in_channel(self):
        return [member.name for member in self.members if member.id in self.channels_info.members]

    def parse(self, text=None):
        match = parse_regex.search(text if text else self.text)
        if match:
            d = match.groupdict()
            return d['target'], d['prop'], d['operator'], d['operand']
        return [None] * 4

    def send(self, message, channel=None):
        slack.api_call('chat.postMessage', channel=channel if channel else self.channel, text=message)

    def update(self, name, prop, operator, operand):
        dbg()
        if operator:
            member_props = PropsBot.props.pop(name, {})
            prop_value = member_props.pop(prop, 0)
            member_props[prop] = PropsBot.operators[operator](prop_value, operand)
            PropsBot.props[name] = member_props
        value = PropsBot.props.get(name, {}).get(prop, 0)
        message = f'{name}:{prop} => {value}'
        self.send(message)

@app.route('/version')
async def version():
    headers = request.headers
    json = await request.get_json(silent=True)
    json = AttrDict(json)
    r1 = slack.api_call('api.test')
    r2 = slack.api_call('auth.test')
    dbg()
    return f'{CFG.APP_VERSION}\n', 200

@app.route('/contribute.json')
async def contribute_json():
    return CONTRIBUTE_JSON, 200

@app.route('/props-bot', methods=['POST'])
async def props_bot():
    form = await request.form.to_dict()
    form = AttrDict(form)
    if not is_request_valid(form.token, form.team_id):
        abort(400)

    return 'wazzup playa?', 200

@app.route('/slack/interactivity', methods=['POST'])
async def slack_interactivity():
    json = await request.get_json(silent=True)
    json = AttrDict(json)
    return Response('', status=200)

@app.route('/slack/message-menus', methods=['POST'])
async def slack_message_menus():
    json = await request.get_json(silent=True)
    json = AttrDict(json)
    return Response('', status=200)

@app.route('/slack/events', methods=['POST'])
async def slack_events():
    print('*'*80)
    json = await request.get_json(silent=True)
    json = AttrDict(json)
    if 'challenge' in json:
        return json.challenge, 200
    if json.event.channel != CFG.PROPS_BOT_CHANNEL_ID and 'text' in json.event:
        return Response('', status=200)
    if json.event.get('username', None) == 'props':
        return Response('', status=200)

    dbg(event=json.event)
    bot = PropsBot(json.event)
    name, prop, operator, operand = bot.parse()
    dbg(name, prop, operator, operand)
    if name in bot.members_in_channel:
        channel = bot.channel
        bot.update(name, prop, operator, operand)
    return Response('', status=200)
