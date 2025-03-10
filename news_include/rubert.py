import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification


class RubertClassifier:

    def __init__(self, snapshot):
        self.tokenizer = AutoTokenizer.from_pretrained(snapshot)
        self.model = AutoModelForSequenceClassification.from_pretrained(snapshot)
        if torch.cuda.is_available():
            self.model.cuda()

    @staticmethod
    def text_preprocess(text):
        text = f"Это статья на тему '{text.strip()}'"
        return text

    def predict(self, text, label_texts, label='entailment', normalize=True):
        tokens = self.tokenizer([self.text_preprocess(text)] * len(label_texts), label_texts, truncation=True, return_tensors='pt', padding=True)
        with torch.inference_mode():
            result = torch.softmax(self.model(**tokens.to(self.model.device)).logits, -1)
        proba = result[:, self.model.config.label2id[label]].cpu().numpy()
        if normalize:
            proba /= sum(proba)
        return proba