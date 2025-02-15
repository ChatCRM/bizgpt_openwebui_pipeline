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
# from gpt_researcher import GPTResearcher
from tavily import TavilyClient

class Pipeline:
    class Valves(BaseModel):
        OPENAI_SECRET_KEY: str
        TAVILY_SECRET_KEY: str

    def __init__(self):
        self.name = "مدل جستجوگر وب"
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
                
                # Skip empty data lines
                if not content.strip():
                    continue
                    
                # Handle complete event with JSON data
                if content.startswith('{'):
                    continue
                    # try:
                    #     import json
                    #     data = json.loads(content)
                    #     if isinstance(data, dict) and 'response' in data:
                    #         yield data['response']
                    #         buffer = ""
                    #         continue
                    # except json.JSONDecoder:
                    #     pass
                
                # Yield the actual content
                if content not in ('**', ':**') and  not content.startswith('{'):  # Skip markdown formatting markers
                    yield content

    
    
    
    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        # This is where you can add your custom RAG pipeline.
        # Typically, you would retrieve relevant information from your knowledge base and synthesize it to generate a response.

        print("Body is: ")
        print(body)
        print("Chat ID is: ")
        print(self.chat_id)

        print("All messages are: ")
        print(messages)
        
        # headers = {'Content-Type': 'application/json', 'Authorization':f'Bearer {self.valves.API_SECRET_KEY}'}
        openai_secret_key = self.valves.OPENAI_SECRET_KEY
        tavily_secret_key = self.valves.TAVILY_SECRET_KEY

        
        try:
            ALLOWED_SEARCH_WEBSITES = [
                "davoudabadi.ir","rc.majlis.ir", "ekhtebar.ir",
                "rrk.ir", "sahoka.azpar.com", "jolt.ut.ac.ir", "vindad.com", 
                "noorlaw.ir", "jplr.atu.ac.ir", "sid.ir", "lri.ir", "bonyadvokala.com", "ensani.ir",
                "dadgaran.com", "jlj.ir", "majdlaw.ir", "majdlaw.ir", "qgl.lri.ir", "clr.modares.ac.ir",
                "sabtjournal.ir", "jhvmn.ir", "lawresearchmagazine.sbu.ac.ir", "sanad.iau.ir", "jclc.sdil.ac.ir",
                "ijmedicallaw.ir", "jplsq.ut.ac.ir", "cld.razavi.ac.ir", "cilamag.ir", "noormags.ir",
            ]
            client = TavilyClient(api_key=tavily_secret_key)
            response = client.search(
                query=user_message, 
                search_depth="advanced",
                include_domains= ALLOWED_SEARCH_WEBSITES,
                include_answer=True
            )
            # Extract sources from results
            sources = [
                {"url": result["url"], "title": result["title"]}
                for result in response.get("results", [])
            ]
            # Make sure we get a string response
            answer = response.get("answer", "No answer provided")
            if not isinstance(answer, str):
                answer = str(answer)
            # Debug print
            print(f"\nTavily Debug - Raw answer: {answer}")
            return self.add_markdown_sources(answer,sources)

        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return "خطایی در سیستم رخ داده است ."

    @staticmethod
    def add_markdown_sources(text, sources):
        source_list = "\n\nمنابع:\n" + "\n".join([f"- [{s['title']}]({s['url']})" for s in sources])
        return text + source_list

# async def fetch_report(query, report_type):
#     """
#     Fetch a research report based on the provided query and report type.
#     """
#     researcher = GPTResearcher(query=query, report_type=report_type, config_path=None)
#     await researcher.conduct_research()
#     report = await researcher.write_report()
#     return report
