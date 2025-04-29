"""
title: Law Researcher
author: open-webui
date: 2024-05-30
version: 1.0
license: MIT
description: A pipeline for retrieving relevant information from a knowledge base using the Haystack library.
requirements: haystack-ai, datasets>=2.6.1, sentence-transformers>=2.2.0
"""
import os
import requests

from typing import List, Union, Generator, Iterator, Optional
from schemas import OpenAIChatMessage

from pydantic import BaseModel
from supabase import create_client, Client
from gpt_researcher import GPTResearcher
from tavily import TavilyClient
import asyncio
import re

class Pipeline:
    class Valves(BaseModel):
        OPENAI_SECRET_KEY: str
        TAVILY_SECRET_KEY: str

    def __init__(self):
        self.name = "مدل محقق"
        self.chat_id = None
        self.valves = self.Valves(
            **{
                "OPENAI_SECRET_KEY": os.getenv("OPENAI_SECRET_KEY", ""),
                "TAVILY_SECRET_KEY": os.getenv("TAVILY_SECRET_KEY", ""),
            }
        )
        pass

    async def on_valves_updated(self):
        # This function is called when the valves are updated.
        # self.valves.VAKILGPT_API_URL = os.getenv("VAKILGPT_API_URL", "http://127.0.0.1:8000/question-answer/submit-stream-v2")
        # self.valves.SUPABASE_URL = os.getenv("SUPABASE_URL", ""),
        # self.valves.SUPABASE_KEY = os.getenv("SUPABASE_KEY", ""),
        pass
    
    async def on_startup(self):
        pass

    async def on_shutdown(self):
        # This function is called when the server is stopped.
        pass

    async def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
      print(f"inlet:{__name__}")
      print(f"user: {user}")
      print(f"body: {body}")
      # Store the chat_id from body
      self.chat_id = body['metadata']['chat_id'] if ('metadata' in body and 'chat_id' in body['metadata']) else body.get('chat_id','')
      print(f"Stored chat_id: {self.chat_id}")

      return body

    @staticmethod
    def stream_sse_response(response):
      """
      Stream and parse Server-Sent Events (SSE) response in real-time.
      
      Args:
          response: The requests response object with stream=True
          
      Yields:
          str: The actual text content as it streams in
      """
      buffer = ""
      
      for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            
            # Skip id, event, and retry lines
            if decoded_line.startswith(('id:', 'event:', 'retry:')):
                continue
                
            # Handle data lines
            if decoded_line.startswith('data: '):
                content = decoded_line[6:]  # Remove 'data: ' prefix
                
                yield content
    
    
    
    async def _async_pipe(self, user_message: str):
      # Original async code here
      researcher = GPTResearcher(query=user_message, report_type="research_report", config_path=None)
      await researcher.conduct_research()
      report = await researcher.write_report()
      return report

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        # This is where you can add your custom RAG pipeline.
        # Typically, you would retrieve relevant information from your knowledge base and synthesize it to generate a response.

        print("Body is: ")
        print(body)
        print("Chat ID is: ")
        print(self.chat_id)
        if not self.chat_id:
            self.chat_id = body['chat_id'] if 'chat_id' in body else None

        print("All messages are: ")
        print(messages)
        
        # headers = {'Content-Type': 'application/json', 'Authorization':f'Bearer {self.valves.API_SECRET_KEY}'}
        openai_secret_key = self.valves.OPENAI_SECRET_KEY
        tavily_secret_key = self.valves.TAVILY_SECRET_KEY
        os.environ['OPENAI_API_KEY'] = openai_secret_key
        os.environ["TAVILY_API_KEY"] = tavily_secret_key

        return asyncio.run(self._async_pipe(user_message + "- respond in Persian language."))

    @staticmethod
    def add_markdown_sources(text, sources):
        source_list = "\n\nمنابع:\n" + "\n".join([f"- [{s['title']}]({s['url']})" for s in sources])
        return text + source_list

async def fetch_report(query, report_type):
    """
    Fetch a research report based on the provided query and report type.
    """
    researcher = GPTResearcher(query=query, report_type=report_type, config_path=None)
    await researcher.conduct_research()
    report = await researcher.write_report()
    return report
