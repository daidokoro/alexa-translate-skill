from boto3 import client
from xml.sax.saxutils import escape
import json
import subprocess
import os
import re
import random


# Alexa Application ID - stored in lambda env variable
app_id = os.environ.get('APPLICATION_ID')

# Define Classes
class Skill:
    '''
    Skill Class handles the interaction between AWS S3 & Polly and the Google Translate Binary.
    '''

    polly = client('polly', region_name='eu-west-1')
    s3 = client('s3')
    bucket = 'alexa-translate'

    # SUpported languages
    lang_spec = {
        'spanish': ('es', 'Conchita'),
        'japanese': ('ja', 'Mizuki'),
        'italian': ('it', 'Carla'),
        'french': ('fr', 'Celine'),
        'german': ('de', 'Marlene')
    }

    # Generic Response strings & examples
    examples = [
        '''Try, I love horses in Spanish"''',
        '''Try, I love cats to Japanese"''',
        '''Try, I love dogs in German"'''
    ]

    err_resp = '''
        I'm Sorry, Project Translate needs both Language and the word you want translated to be specified.

    '''

    def __init__(self, text, lang):
        self.text = text
        self.err = None

        if lang not in Skill.lang_spec.keys():
            self.err = '''
                I'm sorry, I could not identify a language that Project Translate supports.
                I've placed a list of supported languages in your Cards.
            '''
        else:
            self.lang_code = Skill.lang_spec[lang.lower()][0]
            self.voice_id = Skill.lang_spec[lang.lower()][1]
            self.key = "%s_%s.mp3" % (self.text.replace(' ', '_').lower(), self.lang_code)

            # Run
            self._translate()
            if not self._exists():
                self._get_stream()
                self.save_mp3_to_s3()
            self._get_url()


    def _translate(self):
        # Translate text using Go Binary & Google Translate API
        print("Calling translate...")
        cmd = ['./translate', '%s:%s' % (self.lang_code, self.text)]

        self.translation, self.err = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()


    def _get_stream(self):
        # Get voice recording byte data from AWS Polly
        self.response = Skill.polly.synthesize_speech(
            OutputFormat='mp3', #|'ogg_vorbis'|'pcm',
            Text=str(self.translation),
            VoiceId=self.voice_id,
        )['AudioStream'].read()


    def save_mp3(self, m):
        # Save MP3 to disk - Not used in the skill process
        with open(m, 'wb') as f:
            f.write(self.response)


    def save_mp3_to_s3(self):
        # Saves mp3 file to s3 and retreives URL
        print("Saving to S3")
        Skill.s3.put_object(
            Bucket=Skill.bucket,
            Body=self.response,
            Key=self.key,
        )


    def _get_url(self):
        # Gets a presigned url of mp3 via S3
        self.url = escape(Skill.s3.generate_presigned_url(
            ExpiresIn=300,
            ClientMethod='get_object',
            Params={
                'Bucket': Skill.bucket,
                'Key': self.key
            }
        )).encode('utf-8')


    def _exists(self):
        # Return key if translation already exists
        try:

            _ = Skill.s3.get_object(
                Bucket=Skill.bucket,
                Key=self.key
            )

            print("Previous recording detected..")

        except:
            return False
        return True


    @staticmethod
    def Example():
        '''Return random example'''
        return Skill.examples[
            random.randint(0, len(Skill.examples)-1)
        ]

    @staticmethod
    def Parse(body):
        '''Contructs text request from multi-slot input'''

        values = [ v for v in body.values() if 'value' in v.keys() ]
        values.sort(key=lambda k: k['name'])
        text = ' '.join([s['value'] for s in values]).strip(' ')

        # Evaluate last word as the language to translate to
        lang = text.split(' ')[len(text.split(' ')) - 1].lower()

        if lang not in Skill.lang_spec.keys():
            lang = ''

        # remove in <Language> from the end of the string
        text = re.sub('( %s$| in %s$| to %s$)' % (lang, lang, lang), '', text)

        return text, lang

    @staticmethod
    def Response(resp, card_data={}, req_type='PlainText', session_end=True):
        '''Generates response Dict/Json'''
        return {
            'version': '1.0',
            'response': {
                'outputSpeech': {
                    'type': req_type,
                    'text' if req_type == 'PlainText' else 'ssml': resp
                },
                'card':card_data,
                "shouldEndSession": session_end
            },
            'sessionAttributes': {}
        }

    @staticmethod
    def Card(content):
        '''Returns a Simple Card'''
        return {
            "type": "Simple",
            "title": "Translation",
            "content": content
        }

    @staticmethod
    def onTranslate(e={}):
        ''''Runs translate intent'''
        body = e['request']['intent']['slots']

        text, lang = Skill.Parse(body)

        # Return if Language is undefined
        if not lang:
            card = Skill.Card(Skill.err_resp + Skill.Example())

            return Skill.Response(
                Skill.err_resp + Skill.Example(),
                card_data=card,
                session_end=False
            )


        # Getting translation and mp3 url
        print("INFO: Translating --> %s to %s" % (text, lang))
        s = Skill(text, lang)

        if s.err:
            card = Skill.Card(s.err)
            return Skill.Response(s.err, card_data=card)

        print("INFO: Translation --> %s\nMP3 URL --> %s" % (s.translation, s.url))

        resp = '''<speak><audio src='%s' /></speak>''' % s.url
        card = Skill.Card('''"%s" in, %s\n\n%s''' % (text, lang, s.translation))

        return Skill.Response(
            resp,
            card_data=card,
            req_type='SSML',
        )

    @staticmethod
    def onLaunch(e={}):
        '''Runs Launch Intent'''
        welcome_string = 'Welcome to Project Translate. What would you like to translate?\n\n'

        card = Skill.Card(welcome_string)

        return Skill.Response(welcome_string, card_data=card, session_end=False)

    @staticmethod
    def onHelp(e={}):
        return Skill.Response(
            Skill.Example(),
            session_end=False
        )

    @staticmethod
    def onStop(e={}):
        pass
        # return {'shouldEndSession': True, 'sessionAttributes': {}, 'version': '1.0'}


# Intent Map
intent_map = {
    "LaunchRequest": Skill.onLaunch,
    "TranslateIntent": Skill.onTranslate,
    "IntentRequest": Skill.onTranslate,
    "AMAZON.HelpIntent": Skill.onHelp,
    "AMAZON.CancelIntent": Skill.onStop,
    "AMAZON.StopIntent": Skill.onStop,
    "SessionEndedRequest": Skill.onStop
}


# --- AWS Lambda handler
def handle(event, context):
    # for debug print event
    print(event)

    #  Validate App iD
    iD = event['session']['application']['applicationId']

    if (iD != app_id):
        raise ValueError("Invalid Application ID")

    try:
        req = event['request']['intent']['name']
    except:
        req = event['request']['type']


    print("Intent type: %s" % req)
    resp = intent_map[req](e=event)
    print(resp)

    return resp
