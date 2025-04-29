"""
title: Haystack Pipeline
author: open-webui
date: 2024-05-30
version: 1.0
license: MIT
description: A pipeline for retrieving relevant information from a knowledge base using the Haystack library.
requirements: haystack-ai, datasets>=2.6.1, sentence-transformers>=2.2.0
"""
import os
import requests
import re

from typing import List, Union, Generator, Iterator, Optional
from schemas import OpenAIChatMessage

from pydantic import BaseModel
from supabase import create_client, Client

class Pipeline:
    class Valves(BaseModel):
        VAKILGPT_API_URL: str
        API_SECRET_KEY: str
        SUPABASE_URL: str
        SUPABASE_KEY: str
        VAKILGPT_TEST: str = "false"

    def __init__(self):
        self.chat_id = None
        self.name = "مدل آرا قضایی"
        self.valves = self.Valves(
            **{
                "VAKILGPT_API_URL": os.getenv("VAKILGPT_API_URL", "http://127.0.0.1:8000/question-answer/ara-es-only-stream"),
                "API_SECRET_KEY": os.getenv("API_SECRET_KEY", ""),
                "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
                "SUPABASE_KEY": os.getenv("SUPABASE_KEY", ""),
                "VAKILGPT_TEST": os.getenv("VAKILGPT_TEST", "false"),
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
                
                # Process content to handle newlines
                if content not in ('**', ':**') and not content.startswith('{'):  # Skip markdown formatting markers
                    # Convert any escaped newlines to actual newlines
                    processed_content = content
                    if '\\n' in processed_content:
                        processed_content = processed_content.replace('\\n', '\n')
                    if '\\r' in processed_content:
                        processed_content = processed_content.replace('\\r', '\r')
                    
                    # Normalize consecutive newlines (replace more than 2 consecutive newlines with just 2)
                    processed_content = re.sub(r'\n{3,}', '\n\n', processed_content)
                    
                    yield processed_content

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict
    ) -> Union[str, Generator, Iterator]:
        # This is where you can add your custom RAG pipeline.
        # Typically, you would retrieve relevant information from your knowledge base and synthesize it to generate a response.

        print("Body is: ")
        print(body)

        if not self.chat_id:
            self.chat_id = body['chat_id'] if 'chat_id' in body else None
        
        print("Chat ID is: ")
        print(self.chat_id)

        print("All messages are: ")
        print(messages)
        
        headers = {'Content-Type': 'application/json', 'Authorization':f'Bearer {self.valves.API_SECRET_KEY}'}
        url = self.valves.VAKILGPT_API_URL
        supabase_url = self.valves.SUPABASE_URL
        supabase_key = self.valves.SUPABASE_KEY
        is_vakilgpt = self.valves.VAKILGPT_TEST

        
        try:
            supabase: Client = create_client(supabase_url, supabase_key)

            response = supabase.rpc("get_subscription_status",params={'email_param':body['user']['email']}).execute( )
            print("Response is:")
            print(response.data)
            if (bool(response.data) and any([ item['user_limit'] <= 1  for item in list(response.data)])) or is_vakilgpt == "true":
                data = {
                "username": body['user']['email'],
                "question_text": user_message,
                "streamlit_element_key_id": None,
                "chat_id": self.chat_id,
                "user_id": body['user']['id'],
                "messages": [ message for message in messages[-5:] if 'اشتراک فعال نیستید' not in message['content'] ]
                }
                response = requests.post(url, json=data, headers=headers, stream=True)
                # response.raise_for_status()  # Raise an exception for HTTP errors
                return self.stream_sse_response(response)
            else:
                return """
                    ***شما دارای اشتراک فعال نیستید. لطفا از سایت vakilgpt اشتراک تهیه نمایید.***
                    [وکیلیار](https://vakilgpt.info)

                """

        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return "خطایی در سیستم رخ داده است ."

