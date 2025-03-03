import os

from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def shortener(text):
    template = """Rewrite the article given to you in the shortest possible form.

Article:
{article}

Rules:
1. No more than 3 sentences per article.
2. Use only the main points of the article.
3. Respond in Russian.

Answer:"""

    prompt = PromptTemplate(
        template=template,
        input_variables=["article"]
    )

    llm = ChatOpenAI(
        model_name="gpt-4o-mini",
        temperature=0.3,
        max_tokens=256,
        openai_api_key=OPENAI_API_KEY
    )

    chain = prompt | llm
    response = chain.invoke({"article": text})
    return response.content
