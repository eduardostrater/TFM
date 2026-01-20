import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# ✅ Load environment variables
load_dotenv(dotenv_path="_mientorno.env") 
dseek_api_key = os.getenv("DSEEK_API_KEY")
if not dseek_api_key:
    raise ValueError("DSEEK_API_KEY not found in environment variables. Please check _mientorno.env")
llm = ChatOpenAI(model="deepseek-chat", openai_api_key=dseek_api_key, openai_api_base="https://api.deepseek.com")
#llm = ChatOpenAI(model="deepseek-reasoner", openai_api_key=dseek_api_key, openai_api_base="https://api.deepseek.com")
