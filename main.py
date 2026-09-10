import os
import json
import asyncio
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

class Agent:
    def __init__(self, name: str, role: str, api_key: str, endpoint: str):
        self.name = name
        self.role = role
        self.api_key = api_key.strip()
        self.endpoint = endpoint.strip()

    async def speak(self, history: List[Dict[str, str]]) -> str:
        # Prepare contents payload formatted specifically for Gemini API
        gemini_contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })

        payload = {
            "system_instruction": {
                "parts": [{"text": f"You are {self.name}, acting in the role of: {self.role}. Collaborate with other models to fulfill the user's software project request."}]
            },
            "contents": gemini_contents
        }

        # Send API key via header
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        if "example.com" in self.endpoint or not self.api_key:
            await asyncio.sleep(1)
            return f"[{self.role} Proposal] Analyzed current task specs."

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.endpoint, json=payload, headers=headers, timeout=30.0)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                return f"Error ({resp.status_code}): {resp.text}"
            except Exception as e:
                return f"Execution Exception: {str(e)}"

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html not found</h1>"

@app.websocket("/ws/orchestrate")
async def websocket_orchestrate(websocket: WebSocket):
    await manager.connect(websocket)
    conversation_history = []
    
    try:
        while True:
            data_str = await websocket.receive_text()
            payload = json.loads(data_str)
            action = payload.get("action")
            
            if action == "start":
                agents_data = payload.get("agents", [])
                prompt = payload.get("prompt", "")
                rounds = int(payload.get("rounds", 2))
                
                agents = [
                    Agent(a["name"], a["role"], a["api_key"], a["endpoint"]) 
                    for a in agents_data
                ]
                
                conversation_history.append({"role": "user", "content": prompt})
                await manager.broadcast({"type": "system", "text": f"Project Execution Started: {prompt}"})

                for r in range(rounds):
                    await manager.broadcast({"type": "system", "text": f"--- Round {r+1} ---"})
                    
                    for agent in agents:
                        await manager.broadcast({"type": "status", "text": f"{agent.name} is thinking..."})
                        response = await agent.speak(conversation_history)
                        
                        entry = f"[{agent.name} - {agent.role}]: {response}"
                        conversation_history.append({"role": "model", "content": entry})
                        
                        await manager.broadcast({
                            "type": "chat",
                            "agent": agent.name,
                            "role": agent.role,
                            "text": response
                        })
                        
                await manager.broadcast({"type": "system", "text": "Execution round completed."})

            elif action == "step_in":
                guidance = payload.get("guidance", "")
                conversation_history.append({"role": "user", "content": f"[USER INTERVENTION]: {guidance}"})
                await manager.broadcast({"type": "system", "text": f"User Guidance Injected: {guidance}"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)