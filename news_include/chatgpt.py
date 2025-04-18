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


def summarizer(text, themes='any'):
    template = """Summarize the video subtitle transcript given to you.

Transcript:
{transcript}

Themes:
{themes}

Rules:
1. Find news about only given themes in the transcript and list them.
2. Sign all news separately with the corresponding themes.
3. Always add timecode to each news item in format [t=seconds].
4. Respond in Russian.

Answer:"""

    prompt = PromptTemplate(
        template=template,
        input_variables=["transcript", "themes"]
    )

    llm = ChatOpenAI(
        model_name="gpt-4o-mini",
        temperature=0.5,
        max_tokens=2000,
        openai_api_key=OPENAI_API_KEY
    )

    chain = prompt | llm
    response = chain.invoke({"transcript": text, "themes": themes})
    return response.content


def link_finder(text, time):
    template = """Find all links to the news articles *present strictly within* the html page given to you below. Identify news articles based on the link structure (like starting with '/news/') or surrounding context within the provided HTML.

Page:
{page}

Rules:
1. Extract links *only* from the text provided in the `page` variable above. Do not use any external knowledge or generate links.
2. Do not change or fix the links found in the `page` text in any way.
3. Ignore links that are not news articles (e.g., links to categories, tags, non-news sections).
4. Add only links made in this time period: {time} (Analyze dates associated with links if available in the `page` text).
5. In your answer just list the date to each article in %d.%m.%Y format and exact links found separated by comma like this: 25.03.2023;news/article1,15.02.2023;news/article2
6. If there is no date associated with the link, consider it as 0.0.0000

Answer:"""

    prompt = PromptTemplate(
        template=template,
        input_variables=["page", "time"]
    )

    llm = ChatOpenAI(
        model_name="gpt-4o-mini",
        temperature=0.5,
        max_tokens=2048,
        openai_api_key=OPENAI_API_KEY
    )

    chain = prompt | llm
    if time[0] == 'int':
        time = f"last {time[1]} days"
    elif time[0] == 'range':
        time = time[1]
    else:
        time = f"only one day - {time[1]}"
        print(text, time)
    response = chain.invoke({"page": text, "time": time})
    return response.content