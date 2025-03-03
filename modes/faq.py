import os
import pandas as pd
from aiogram.types import Message
from aiogram.enums import ContentType
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

vectorstore = None
qa_chain = None


def load_faq_data():
    """Loads FAQ data from CSV and initializes vector store"""
    global vectorstore, qa_chain
    data = pd.read_csv("test/qa.csv")

    texts = [f"problem: {row['question']}\nanswer_variant: {row['answer']}"
             for _, row in data.iterrows()]
    metadatas = [{"answer_variant": row["answer"]} for _, row in data.iterrows()]

    embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    vectorstore = FAISS.from_texts(texts, embeddings, metadatas=metadatas)

    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    # Custom prompt template
    template = """You are a technical assistant. Analyze the provided answers and generate a final response.

Context:
{context}

Question:
{question}

Rules:
1. If the question is unrelated to technical support, inform the user.
2. If no answer is found, return "🤷". If it's obvious, answer logically.
3. Respond in Russian.

Answer:"""

    QA_PROMPT = PromptTemplate(
        template=template,
        input_variables=["context", "question"]
    )

    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.3, max_tokens=128)
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        chain_type_kwargs={"prompt": QA_PROMPT},
        return_source_documents=True,
    )


# Load FAQ data on startup
load_faq_data()


async def process_message(message: Message, bot):
    """Handles incoming messages in FAQ mode"""
    user_question = message.text

    if user_question.startswith("/update"):
        load_faq_data()
        await message.reply("✅ База знаний обновлена!")
        return

    elif message.content_type == ContentType.DOCUMENT:
        document = message.document

        if not document.file_name.endswith(".csv"):
            await message.reply("⚠️ Пожалуйста, загрузите CSV-файл.")
            return

        file_path = "../test/qa.csv"
        file = await bot.get_file(document.file_id)
        file_content = await bot.download_file(file.file_path)
        with open(file_path, "wb") as f:
            f.write(file_content.getvalue())

        load_faq_data()
        await message.reply("✅ Файл получен! База знаний обновлена!")
        return

    # Process normal text question
    result = qa_chain.invoke({"query": user_question})
    response_text = result["result"]

    await message.reply('mode1:\n ' + response_text)
