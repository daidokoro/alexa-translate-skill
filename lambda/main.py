from boto3 import client
from xml.sax.saxutils import escape
import json
import subprocess
import os
import re


# Alexa Application ID - stored in lambda env variable
app_id = os.environ.get('APPLICATION_ID')

# Define Classes
class SkillRequest:
    '''
    SkillRequest Class handles the interaction between AWS S3 & Polly and the Google Translate Binary.
    '''

    region = 'eu-west-1'
    polly = client('polly', region_name=region)
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

    # Generic Response strings
    example = '''
        Try, "Simply Translate I believe I can fly in spanish"
    '''

    err_resp = '''
        I'm Sorry, Simply Translate needs both Language and the word you want translated to be specified.

    ''' + example

    def __init__(self, text, lang):
        self.text = text
        self.err = None

        if lang not in SkillRequest.lang_spec.keys():
            self.err = '''
                I'm sorry, I could not identify a language that Simply Translate supports.
                I've placed a list of supported languages in your Cards.
            '''
        else:
            self.lang_code = SkillRequest.lang_spec[lang.lower()][0]
            self.voice_id = SkillRequest.lang_spec[lang.lower()][1]

            # Run
            self._translate()
            self._get_stream()
            self.save_mp3_to_s3()
            self._get_url()

    def _translate(self):
        # Translate text using Go Binary & Google Translate API
        cmd = ['./translate', '-l', self.lang_code, '-t', self.text]

        self.translation, self.err = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()


    def _get_stream(self):
        # Get voice recording byte data from AWS Polly
        self.response = SkillRequest.polly.synthesize_speech(
            OutputFormat='mp3', #|'ogg_vorbis'|'pcm',
            Text=self.translation,
            VoiceId=self.voice_id,
        )['AudioStream'].read()

    def save_mp3(self, m):
        # Save MP3 to disk - Not used in the skill process
        with open(m, 'wb') as f:
            f.write(self.response)


    def save_mp3_to_s3(self):
        # Saves mp3 file to s3 and retreives URL
        self.key = "%s_%s.mp3" % (self.text.replace(' ', '').lower(), self.lang_code)
        SkillRequest.s3.put_object(
            Bucket=SkillRequest.bucket,
            Body=self.response,
            Key=self.key
        )


    def _get_url(self):
        # Gets a presigned url of mp3 via S3
        self.url = escape(SkillRequest.s3.generate_presigned_url(
            ExpiresIn=300,
            ClientMethod='get_object',
            Params={
                'Bucket': SkillRequest.bucket,
                'Key': self.key
            }
        )).encode('utf-8')


    @staticmethod
    def Parse(body):
        '''Contructs text request from multi-slot input'''

        values = [ v for v in body.values() if 'value' in v.keys() ]
        values.sort(key=lambda k: k['name'])
        text = ' '.join([s['value'] for s in values]).strip(' ')

        # Evaluate last word as the language to translate to
        lang = text.split(' ')[len(text.split(' ')) - 1].lower()

        if lang not in SkillRequest.lang_spec.keys():
            lang = ''

        # remove in <Language> from the end of the string
        text = re.sub('( %s$| in %s$| to %s$)' % (lang, lang, lang), '', text)

        return text, lang


    @staticmethod
    def Response(resp, card_data={}, req_type='PlainText'):
        '''Generates response Dict/Json'''
        return {
            'version': '1.0',
            'response': {
                'outputSpeech': {
                    'type': req_type,
                    'text' if req_type == 'PlainText' else 'ssml': resp
                },
                'card':card_data,
                "shouldEndSession": True
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
    def onTranslate(text, lang):
        ''''Runs translate intent'''
        # Getting translation and mp3 url
        print("INFO: Translating --> %s to %s" % (text, lang))
        s = SkillRequest(text, lang)

        if s.err:
            card = SkillRequest.Card(s.err)
            return SkillRequest.Response(s.err, card_data=card)

        print("INFO: Translation --> %s\nMP3 URL --> %s" % (s.translation, s.url))

        resp = '''<speak><s>%s in, %s</s> <audio src='%s' /></speak>''' % (s.text, lang, s.url)
        card = SkillRequest.Card("%s in, %s\n\n%s" % (text, lang, s.translation))

        return SkillRequest.Response(
            resp,
            card_data=card,
            req_type='SSML'
        )


    @staticmethod
    def onLaunch():
        '''Runs Launch Intent'''
        welcome_string = 'Welcome to Simply Translate.\n\n'

        welcome_string += SkillRequest.example

        card = SkillRequest.Card(welcome_string)

        return SkillRequest.Response(welcome_string, card_data=card)



# --- AWS Lambda handler
def handler(event, context):
    # for debug print event
    print(event)

    #  Validate App iD
    _id = event['session']['application']['applicationId']
    if (_id != app_id):
        raise ValueError("Invalid Application ID")

    req_type = event['request']['type']

    print("Intent type: %s" % req_type)

    if 'IntentRequest'.lower() in req_type.lower():
        body = event['request']['intent']['slots']

        text, lang = SkillRequest.Parse(body)

        if not lang:
            card = SkillRequest.Card(SkillRequest.err_resp)
            return SkillRequest.Response(SkillRequest.err_resp, card_data=card)

        # Getting translation and mp3 url
        return SkillRequest.onTranslate(text, lang)

    elif 'LaunchRequest'.lower() in req_type.lower():
        print('something')
        return SkillRequest.onLaunch()

    else:
        # Assume session end at this point - empty response
        return SkillRequest.Response("")
