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

from typing import List, Union, Generator, Iterator, Optional
from schemas import OpenAIChatMessage

from pydantic import BaseModel

class Pipeline:
    class Valves(BaseModel):
        VAKILGPT_API_URL: str
        API_SECRET_KEY: str
    def __init__(self):
        self.chat_id = None
        self.valves = self.Valves(
            **{
                "VAKILGPT_API_URL": os.getenv("VAKILGPT_API_URL", "http://127.0.0.1:8000/question-answer/submit-stream-v2"),
                "API_SECRET_KEY": os.getenv("API_SECRET_KEY", ""),
            }
        )
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
      self.chat_id = body.get("chat_id")
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
        
        headers = {'Content-Type': 'application/json', 'Authorization':f'Bearer {self.valves.API_SECRET_KEY}'}
        url = self.valves.VAKILGPT_API_URL
        data = {
          "username": body['user']['email'],
          "question_text": user_message,
          "streamlit_element_key_id": None,
          "chat_id": self.chat_id,
          "user_id": body['user']['id']
        }
        try:
            # Initiating a POST request with streaming enabled
            response = requests.post(url, json=data, headers=headers, stream=True)
            # response.raise_for_status()  # Raise an exception for HTTP errors
            return self.stream_sse_response(response)
            # full_response = ''
            # for line in response.iter_lines():
            #     if line:
            #         full_response += line.decode('utf-8') + '\n'

            # # Parse the response to get just the final text
            # final_text = self.parse_sse_response(full_response)
            # return final_text

        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return "Error..."
