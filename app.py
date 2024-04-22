import os
import json
import time
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
from flyflowclient import OpenAI

app = FastAPI()

client = OpenAI(
    base_url="https://api.flyflow.dev/v1",
    api_key='demo'
)

message_arrays = {}

class LLMMock:
    def __init__(self, call_id):
        self.call_id = call_id
        self.messages = message_arrays[call_id]

    def draft_begin_messsage(self):
        self.messages.append({"role": "assistant", "content": "Hey there, how can I help you?"})
        return {
            "response_id": 0,
            "content": "Hey there, how can I help you?",
            "content_complete": True,
            "end_call": False,
        }

    def draft_response(self, request):
        content = request["transcript"][-1]["content"]
        self.messages.append({"role": "user", "content": content})

        start_time = time.time()  # Start the timer

        chat_completion = client.chat.completions.create(
            # model="gpt-4-turbo",
            model="flyflow-voice-small",
            messages=self.messages,  # Use only the last 5 messages
        )
        response = chat_completion.choices[0].message.content
        self.messages.append({"role": "assistant", "content": response})

        end_time = time.time()  # Stop the timer
        execution_time = end_time - start_time

        yield {
            "response_id": request['response_id'],
            "content": response,
            "content_complete": True,
            "end_call": False,
        }

@app.websocket("/llm-websocket/{call_id}")
async def websocket_handler(websocket: WebSocket, call_id: str):
    await websocket.accept()
    print(f"Handle llm ws for: {call_id}")

    if call_id not in message_arrays:
        message_arrays[call_id] = [
            {"role": "system", "content": """
            You are a technical support specialist for flyflow. *Respond in one sentence or less*
            
            About flyflow
            
            Flyflow is the ultimate API for LLMs. Our goal is to make it so your engineers get to focus on product and not infra. When building on top of LLMs, builders care about the following:

            Response quality
            Latency (both time to first token and tokens / second)
            Rate limits
            Reliability
            Enterprise grade security
            Flyflow is designed to optimize for all of these qualities, built to be open source, high performance written in golang, and optionally self-hosted for maximum flexiblity.
            
            How it Works
            Underneath, flyflow is a model optimization / fine tuning service that creates a custom, fast and cheap model for voice use cases. Our APIs support many different models from the smallest 7b models to GPT4 and Claude3. We serve all of your LLM calls through api.flyflow.dev and while we're serving the calls we collect the data that we can later use for evals and fine tuning.
            
            Once we've collected enough data, we use that data to do fine tuning and evals to build you a custom model that matches GPT4 or Claude3 quality while being significantly cheaper, faster, and more reliable.
            
            ONLY respond in one sentence
            """},
        ]

    llm_client = LLMMock(call_id)

    # send first message to signal ready of server
    response_id = 0
    first_event = llm_client.draft_begin_messsage()
    await websocket.send_text(json.dumps(first_event))

    async def stream_response(request):
        nonlocal response_id
        for event in llm_client.draft_response(request):
            await websocket.send_text(json.dumps(event))
            if request['response_id'] < response_id:
                return  # new response needed, abandon this one

    try:
        while True:
            message = await websocket.receive_text()
            request = json.loads(message)
            # print out transcript
            os.system('cls' if os.name == 'nt' else 'clear')

            if 'response_id' not in request:
                continue  # no response needed, process live transcript update if needed
            response_id = request['response_id']
            asyncio.create_task(stream_response(request))
    except WebSocketDisconnect:
        print(f"LLM WebSocket disconnected for {call_id}")
    except Exception as e:
        print(f'LLM WebSocket error for {call_id}: {e}')
    finally:
        print(f"LLM WebSocket connection closed for {call_id}")
        del message_arrays[call_id]  # Remove the message array for the closed call

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0:0:0:0", port=5000)