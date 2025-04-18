import nltk
import traceback

try:
    nltk.data.find('tokenizers/punkt')
except:
    nltk.download('punkt')
