from boto3 import client
from xml.sax.saxutils import escape
import json
import subprocess
import os


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

    lang_spec = {
        'spanish': ('es', 'Penelope'),
        'japanese': ('ja', 'Mizuki')
    }

    def __init__(self, text, lang='spanish'):
        self.text = text
        self.err = None

        if lang not in SkillRequest.lang_spec.keys():
            self.err = "I'm sorry, Pablo only translates Japanese and Spanish."
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
    def Translate(text, lang):
        ''''Runs translate intent'''
        # Getting translation and mp3 url
        s = SkillRequest(text, lang)

        if s.err:
            return {
                'version': '1.0',
                'response': {
                    'outputSpeech': {
                        'type': 'PlainText',
                        'text': s.err
                    },
                    "shouldEndSession": True
                },
                'card':{},
                'sessionAttributes': {}
            }

        print("INFO: Translation --> %s\nMP3 URL --> %s" % (s.translation, s.url))

        return {
            'version': '1.0',
            'response': {
                'outputSpeech': {
                    'type': 'SSML',
                    'ssml': '''<speak>%s in %s. <audio src='%s' /></speak>''' % (s.text, lang, s.url)
                },
                'card':{
                    "type": "Simple",
                    "title": "Translation",
                    "content": "%s in %s is %s" % (text, lang, s.translation)
                },
                "shouldEndSession": True
            },
            'sessionAttributes': {}
        }



# --- AWS Lambda handler
def handler(event, context):
    # Verify app id
    print(event)

    _id = event['session']['application']['applicationId']
    if (_id != app_id):
        raise ValueError("Invalid Application ID")

    # intent = event['request']['intent']['name']
    text = event['request']['intent']['slots']['text']['value']
    lang = event['request']['intent']['slots']['lang']['value']

    # Translating
    print("INFO: Translating --> %s to %s" % (text, lang))

    # Getting translation and mp3 url
    return SkillRequest.Translate(text, lang)
