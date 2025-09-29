from fastapi import FastAPI, Request, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from langchain_cerebras import ChatCerebras
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from dotenv import load_dotenv
import os
import json
import uuid
import subprocess
import asyncio
import aiohttp
from typing import Optional, List, Dict, Any
import re
from json_repair import repair_json
import ast
from datetime import datetime
load_dotenv()

# Import RAG service
try:
    from backend.rag_service import get_rag_service
except ImportError:
    from rag_service import get_rag_service

# Ensure env var is present but do not crash app on missing key
_cerebras_api_key = os.getenv("CEREBRAS_API_KEY")
if _cerebras_api_key:
    os.environ["CEREBRAS_API_KEY"] = _cerebras_api_key

def get_llm(model: str = "llama-4-maverick-17b-128e-instruct", timeout: int = 30) -> ChatCerebras:
    """
    Lazily initialize the LLM so the app can start even if the key is missing
    Default model: llama-4-maverick-17b-128e-instruct (Llama 4 Maverick, optimized for code generation)
    This model is used across all endpoints for consistency and best performance
    """
    if not os.getenv("CEREBRAS_API_KEY"):
        raise HTTPException(status_code=500, detail="CEREBRAS_API_KEY not configured")
    try:
        return ChatCerebras(model=model, timeout=timeout, max_retries=1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize LLM: {str(e)}")

def check_docker_daemon() -> None:
    """Check if Docker daemon is running"""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=503,
                detail="Docker daemon is not running. Please start Docker Desktop or ensure Docker is accessible."
            )
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Docker is not installed or not in PATH. Please install Docker Desktop."
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=503,
            detail="Docker check timed out. Ensure Docker is running."
        )


def strip_code_blocks(text: str) -> str:
    """Remove markdown code fences so chat replies stay concise."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PlanRequest(BaseModel):
    description: str

class CommandData(BaseModel):
    name: str
    description: str

class GenerateData(BaseModel):
    description: str
    discordToken: str
    applicationId: str
    project_id: Optional[str] = None
    commands: Optional[List[CommandData]] = None
    prefix: Optional[str] = "!"
    user_id: Optional[str] = None

class ValidateDiscordRequest(BaseModel):
    token: str
    application_id: str

class FileSpec(BaseModel):
    path: str
    content: str

class FileWriteRequest(BaseModel):
    path: str
    content: str

class FileDeleteRequest(BaseModel):
    path: str

class ContainerStartRequest(BaseModel):
    project_id: str

class ContainerStopRequest(BaseModel):
    project_id: str

class AIAssistRequest(BaseModel):
    project_id: str
    message: str
    file_tree: Optional[List[Dict[str, Any]]] = None
    conversation_history: Optional[List[Dict[str, str]]] = None

class RailwayDeployRequest(BaseModel):
    project_id: str

# Workspace root (can be overridden via WORKSPACE_ROOT env)
WORKSPACE_ROOT = os.getenv(
    "WORKSPACE_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspace")),
)

# Database files
DB_DIR = os.path.join(os.path.dirname(__file__), "db")
USERS_DB = os.path.join(DB_DIR, "users.json")
PROJECTS_DB = os.path.join(DB_DIR, "projects.json")

# Track running containers: {project_id: container_id}
running_containers: Dict[str, str] = {}

# Initialize RAG service on startup
rag_service = get_rag_service()

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    print("[STARTUP] Initializing RAG service...")
    try:
        rag_service.initialize()
        print("[STARTUP] ✅ RAG service initialized successfully")
    except Exception as e:
        print(f"[STARTUP] ⚠️ RAG initialization failed: {e}")
        print("[STARTUP] Bot generation will proceed without template retrieval")

# ===== DATABASE FUNCTIONS =====

def init_db():
    """Initialize database files if they don't exist"""
    os.makedirs(DB_DIR, exist_ok=True)
    if not os.path.exists(USERS_DB):
        with open(USERS_DB, 'w') as f:
            json.dump({}, f)
    if not os.path.exists(PROJECTS_DB):
        with open(PROJECTS_DB, 'w') as f:
            json.dump({}, f)

def load_users() -> Dict[str, Any]:
    """Load users from database"""
    try:
        with open(USERS_DB, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users: Dict[str, Any]):
    """Save users to database"""
    with open(USERS_DB, 'w') as f:
        json.dump(users, f, indent=2)

def load_projects() -> Dict[str, Any]:
    """Load projects from database"""
    try:
        with open(PROJECTS_DB, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_projects(projects: Dict[str, Any]):
    """Save projects to database"""
    with open(PROJECTS_DB, 'w') as f:
        json.dump(projects, f, indent=2)

def ensure_user_exists(user_id: str):
    """Ensure user exists in database"""
    users = load_users()
    if user_id not in users:
        users[user_id] = {
            "projects": [],
            "created_at": datetime.now().isoformat()
        }
        save_users(users)

def add_project_to_user(user_id: str, project_id: str):
    """Add project to user's project list"""
    users = load_users()
    if user_id not in users:
        ensure_user_exists(user_id)
        users = load_users()

    if project_id not in users[user_id]["projects"]:
        users[user_id]["projects"].append(project_id)
        save_users(users)

def save_project_metadata(project_id: str, user_id: str, name: str, description: str, application_id: str = None):
    """Save project metadata to database"""
    projects = load_projects()
    projects[project_id] = {
        "user_id": user_id,
        "name": name,
        "description": description,
        "application_id": application_id,
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "modified_at": datetime.now().isoformat()
    }
    save_projects(projects)
    add_project_to_user(user_id, project_id)

def get_user_projects(user_id: str) -> List[Dict[str, Any]]:
    """Get all projects for a user"""
    users = load_users()
    projects = load_projects()

    if user_id not in users:
        return []

    user_project_ids = users[user_id]["projects"]
    user_projects = []

    for project_id in user_project_ids:
        if project_id in projects:
            project = projects[project_id].copy()
            project["id"] = project_id
            user_projects.append(project)

    # Sort by modified_at descending
    user_projects.sort(key=lambda x: x.get("modified_at", ""), reverse=True)
    return user_projects

def get_project_metadata(project_id: str) -> Optional[Dict[str, Any]]:
    """Get project metadata"""
    projects = load_projects()
    if project_id in projects:
        project = projects[project_id].copy()
        project["id"] = project_id
        return project
    return None

def update_project_modified(project_id: str):
    """Update project's last modified timestamp"""
    projects = load_projects()
    if project_id in projects:
        projects[project_id]["modified_at"] = datetime.now().isoformat()
        save_projects(projects)

# Initialize database on startup
init_db()

def get_project_dir(project_id: str) -> str:
    return os.path.join(WORKSPACE_ROOT, project_id)

def ensure_directory_exists(directory_path: str) -> None:
    os.makedirs(directory_path, exist_ok=True)

def safe_join(base_dir: str, relative_path: str) -> str:
    """Prevent path traversal outside the workspace"""
    normalized_path = os.path.normpath(os.path.join(base_dir, relative_path))
    if not normalized_path.startswith(os.path.abspath(base_dir)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return normalized_path

def write_file(base_dir: str, relative_path: str, content: str) -> None:
    abs_path = safe_join(base_dir, relative_path)
    ensure_directory_exists(os.path.dirname(abs_path))
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)

def read_file_from_workspace(base_dir: str, relative_path: str) -> str:
    abs_path = safe_join(base_dir, relative_path)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()

def delete_path(base_dir: str, relative_path: str) -> None:
    abs_path = safe_join(base_dir, relative_path)
    if not os.path.exists(abs_path):
        return
    if os.path.isdir(abs_path):
        # Only delete empty dirs via this API to be safe
        try:
            os.rmdir(abs_path)
        except OSError:
            raise HTTPException(status_code=400, detail="Directory not empty")
    else:
        os.remove(abs_path)

def build_tree(root_dir: str, base_prefix: str = "") -> List[Dict[str, Any]]:
    tree: List[Dict[str, Any]] = []
    if not os.path.exists(root_dir):
        return tree
    for name in sorted(os.listdir(root_dir)):
        abs_path = os.path.join(root_dir, name)
        rel_path = os.path.join(base_prefix, name) if base_prefix else name
        if os.path.isdir(abs_path):
            node = {
                "type": "dir",
                "name": name,
                "path": rel_path,
                "children": build_tree(abs_path, rel_path),
            }
        else:
            node = {"type": "file", "name": name, "path": rel_path}
        tree.append(node)
    return tree

def validate_python_syntax(code: str, filepath: str = "file.py") -> Optional[str]:
    """
    Validate Python syntax. Returns error message if invalid, None if valid.
    """
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        error_msg = f"SyntaxError in {filepath} at line {e.lineno}: {e.msg}"
        if e.text:
            error_msg += f"\n  {e.text.strip()}"
        return error_msg
    except Exception as e:
        return f"Error validating {filepath}: {str(e)}"

def fix_python_syntax_with_ai(code: str, error_msg: str, filepath: str) -> str:
    """
    Use AI to fix Python syntax errors
    """
    try:
        llm = get_llm(model="llama-4-maverick-17b-128e-instruct")
        fix_prompt = ChatPromptTemplate.from_template(
            """You are a Python syntax error fixer. Fix ONLY the syntax errors in the code below.

ORIGINAL CODE WITH ERROR:
{code}

ERROR MESSAGE:
{error_msg}

INSTRUCTIONS:
1. Fix ONLY syntax errors (unterminated strings, missing quotes, brackets, etc.)
2. Do NOT change the logic or functionality
3. Keep all the original code structure and variable names
4. Return ONLY the fixed Python code, NO explanations or markdown
5. Do NOT wrap the code in ```python blocks
6. The code should be ready to write directly to a .py file

COMMON FIXES:
- Unterminated strings: Add missing quotes
- f-strings with quotes: Use triple quotes or escape properly
- Missing parentheses/brackets: Add them
- Indentation errors: Fix spacing

Return the complete fixed code:"""
        )
        
        messages = fix_prompt.invoke({
            "code": code,
            "error_msg": error_msg
        })
        response = llm.invoke(messages)
        fixed_code = response.content.strip()
        
        # Remove markdown code fences if present
        if fixed_code.startswith("```"):
            lines = fixed_code.split('\n')
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            fixed_code = '\n'.join(lines)
        
        return fixed_code
    except Exception as e:
        print(f"[FIX] Failed to fix syntax with AI: {e}")
        return code  # Return original if fix fails

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

@app.post("/test-cors")
async def test_cors(data: dict = None):
    """Simple endpoint to test CORS without requiring API keys"""
    return {"message": "CORS is working!", "data": data}

@app.post("/validate-discord")
async def validate_discord(data: ValidateDiscordRequest):
    """Validate Discord token and application ID"""
    headers = {"Authorization": f"Bot {data.token}"}

    try:
        async with aiohttp.ClientSession() as session:
            # Validate token by fetching bot user info
            async with session.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return {"valid": False, "error": "Invalid bot token"}

                bot_data = await resp.json()
                bot_id = bot_data.get("id")
                bot_name = bot_data.get("username")

                # Verify the bot ID matches the application ID
                if bot_id != data.application_id:
                    return {
                        "valid": False,
                        "error": f"Bot ID ({bot_id}) does not match Application ID ({data.application_id})"
                    }

                # Get bot avatar
                bot_avatar = bot_data.get("avatar")
                avatar_url = f"https://cdn.discordapp.com/avatars/{bot_id}/{bot_avatar}.png" if bot_avatar else f"https://cdn.discordapp.com/embed/avatars/{int(bot_id) % 6}.png"

                return {
                    "valid": True,
                    "bot_name": bot_name,
                    "bot_id": bot_id,
                    "bot_avatar": avatar_url
                }
    except asyncio.TimeoutError:
        return {"valid": False, "error": "Request timed out"}
    except Exception as e:
        return {"valid": False, "error": f"Validation failed: {str(e)}"}

@app.post("/plan")
async def create_plan(data: PlanRequest):
    """Generate a command plan using AI - FAST with Cerebras"""
    import time
    start = time.time()

    print(f"[PLAN] Generating plan for: {data.description[:50]}...")

    try:
        llm = get_llm(model="llama-4-maverick-17b-128e-instruct", timeout=15)  # 15s timeout
        print(f"[PLAN] LLM initialized, sending request...")

        plan_prompt = ChatPromptTemplate.from_template(
            """Generate Discord bot commands for this request. Return ONLY JSON, no markdown.

REQUEST: {description}

JSON format:
{{"prefix":"!","commands":[{{"name":"help","description":"Shows commands"}},{{"name":"ping","description":"Bot latency"}},{{"name":"command3","description":"..."}}]}}

Make 5-8 commands relevant to the request. Return JSON only:"""
        )

        messages = plan_prompt.invoke({"description": data.description})
        print(f"[PLAN] Calling Cerebras API...")

        response = llm.invoke(messages)
        raw_text = response.content.strip()
        print(f"[PLAN] Got response: {len(raw_text)} chars")

        # Clean JSON
        raw_text = re.sub(r"```(?:json)?", "", raw_text).strip()

        plan = json.loads(raw_text)
        commands = plan.get("commands", [])
        prefix = plan.get("prefix", "!")

        elapsed = time.time() - start
        print(f"[PLAN] ⚡ Generated {len(commands)} commands in {elapsed:.2f}s")

        return {
            "prefix": prefix,
            "commands": commands
        }
    except asyncio.TimeoutError:
        print(f"[PLAN] ❌ Timeout after {time.time() - start:.2f}s")
        return {
            "prefix": "!",
            "commands": [
                {"name": "help", "description": "Shows all available commands"},
                {"name": "ping", "description": "Shows bot latency"}
            ]
        }
    except json.JSONDecodeError as e:
        print(f"[PLAN] ❌ Parse error: {e}")
        return {
            "prefix": "!",
            "commands": [
                {"name": "help", "description": "Shows all available commands"},
                {"name": "ping", "description": "Shows bot latency"}
            ]
        }
    except Exception as e:
        print(f"[PLAN] ❌ Error: {type(e).__name__}: {e}")
        return {
            "prefix": "!",
            "commands": [
                {"name": "help", "description": "Shows all available commands"},
                {"name": "ping", "description": "Shows bot latency"}
            ]
        }

@app.post("/generate")
async def generate(data: GenerateData):
    import time
    start_time = time.time()
    print(f"\n{'='*60}")
    print(f"[GENERATE] Starting generation for project...")

    llm = get_llm(model="qwen-3-coder-480b")  # Qwen 3 Coder 480B - specialized for code generation
    print(f"[GENERATE] ⏱️  LLM initialized in {time.time() - start_time:.2f}s")

    project_id = data.project_id or uuid.uuid4().hex[:12]
    project_dir = get_project_dir(project_id)
    ensure_directory_exists(project_dir)
    print(f"[GENERATE] Project ID: {project_id}")

    # CRITICAL: Stop any existing container for this project before regenerating
    cleanup_start = time.time()
    container_name = f"bot-{project_id}"
    try:
        print(f"[GENERATE] Stopping any existing container: {container_name}")
        try:
            # Try graceful stop with short timeout
            subprocess.run(
                ["docker", "stop", "-t", "5", container_name],
                capture_output=True,
                timeout=8
            )
        except subprocess.TimeoutExpired:
            # Force kill if graceful stop fails
            print(f"[GENERATE] Graceful stop timed out, force killing...")
            subprocess.run(
                ["docker", "kill", container_name],
                capture_output=True,
                timeout=5
            )

        subprocess.run(
            ["docker", "rm", container_name],
            capture_output=True,
            timeout=10
        )
        print(f"[GENERATE] ✅ Cleaned up old container in {time.time() - cleanup_start:.2f}s")
    except Exception as e:
        print(f"[GENERATE] Container cleanup: {e} (might not exist, ok to continue)")

    # Clean up from tracking dict
    if project_id in running_containers:
        del running_containers[project_id]

    # Use commands from frontend if provided, otherwise use defaults
    prefix = data.prefix or "!"

    if data.commands:
        # Format CommandData objects
        command_list = [f"{prefix}{cmd.name} - {cmd.description}" for cmd in data.commands]
    else:
        # Default commands
        command_list = [f"{prefix}help - Show available commands", f"{prefix}ping - Check bot status"]

    # ===== RAG INTEGRATION: Retrieve relevant templates =====
    rag_start = time.time()
    relevant_templates = []
    templates_context = ""
    
    try:
        print(f"[GENERATE] 🔍 Retrieving relevant templates from RAG...")
        relevant_templates = rag_service.get_relevant_templates(
            user_query=data.description,
            k=3  # Top 3 most relevant templates
        )
        
        if relevant_templates:
            templates_context = rag_service.format_templates_for_prompt(relevant_templates)
            print(f"[GENERATE] ✅ Retrieved {len(relevant_templates)} templates in {time.time() - rag_start:.2f}s")
        else:
            print(f"[GENERATE] ⚠️ No relevant templates found, proceeding without examples")
            templates_context = "No specific template examples found. Generate from scratch using best practices."
            
    except Exception as e:
        print(f"[GENERATE] ⚠️ RAG retrieval failed: {e}")
        print(f"[GENERATE] Proceeding without template guidance")
        templates_context = "Template retrieval unavailable. Generate using Discord.py best practices."

    # Generate bot code with specified commands AND template guidance
    prompt = ChatPromptTemplate.from_template(
        """You are an expert Discord.py code generator. Generate COMPLETE, WORKING Discord bots with REAL DATA FUNCTIONALITY.

=== OUTPUT FORMAT (CRITICAL - READ FIRST) ===
Return a SINGLE JSON object starting with {{ (NOT an array starting with [):
{{
  "summary": "Brief bot description",
  "features": ["command1", "command2", "command3"],
  "structure": {{"files": ["main.py", "requirements.txt", "data.json"], "description": "File organization"}},
  "files": [
    {{"path": "main.py", "content": "COMPLETE WORKING CODE HERE"}},
    {{"path": "requirements.txt", "content": "discord.py>=2.3.2\\npython-dotenv>=1.0.0"}},
    {{"path": "data.json", "content": "{{\\"users\\": {{}}}}"}}
  ]
}}

=== USER REQUEST ===
{description}

COMMANDS: {commands}
PREFIX: {prefix}

=== REFERENCE TEMPLATES ===
{templates_context}

Use these templates as structural guides - ADAPT their data persistence, error handling, and command patterns to fit the user's request. DO NOT copy features directly.

=== CODE GENERATION RULES ===

1. **EMBED RESPONSES WITH REAL DATA** (MOST IMPORTANT):
   - ✅ EVERY command MUST use discord.Embed for responses
   - ✅ Embeds MUST display ACTUAL DATA from your data structures (stats, items, balances, etc.)
   - ❌ NEVER use placeholder text like "Profile viewed!" or "Command executed!"

   Example - BAD:
   ```python
   embed = discord.Embed(description="Profile viewed!")
   ```

   Example - GOOD:
   ```python
   user_data = load_data()
   stats = user_data.get(str(ctx.author.id), {{}})
   embed = discord.Embed(title=f"{{ctx.author.name}}'s Profile", color=discord.Color.blue())
   embed.add_field(name="Level", value=stats.get('level', 1), inline=True)
   embed.add_field(name="XP", value=stats.get('xp', 0), inline=True)
   embed.add_field(name="Balance", value=f"${{stats.get('balance', 0)}}", inline=True)
   await ctx.send(embed=embed)
   ```

2. **DATA PERSISTENCE**:
   - Create data.json with appropriate structure for your bot's features
   - Use load_data() and save_data() helper functions in main.py
   - Initialize user data with default values on first command use
   - Store meaningful data: user IDs as keys, nested dicts for complex state

3. **COMMAND INTERLINKING**:
   - Commands should share and modify the same data structures
   - Example: economy bot → !work earns coins, !shop spends coins, !balance shows coins
   - Validate state (e.g., check if user has enough balance before purchase)

4. **REQUIRED CODE STRUCTURE** (main.py):
   ```python
   import os
   from dotenv import load_dotenv
   load_dotenv()

   import discord
   from discord.ext import commands
   import json
   from typing import Dict, Any

   # Data persistence helpers
   def load_data() -> Dict[str, Any]:
       try:
           with open('data.json', 'r') as f:
               return json.load(f)
       except FileNotFoundError:
           return {{}}

   def save_data(data: Dict[str, Any]):
       with open('data.json', 'w') as f:
           json.dump(data, f, indent=2)

   # Bot setup
   intents = discord.Intents.default()
   intents.message_content = True
   bot = commands.Bot(command_prefix='{prefix}', intents=intents, help_command=None)

   @bot.event
   async def on_ready():
       print(f'Logged in as {{bot.user}}')

   @bot.command()
   async def help(ctx):
       embed = discord.Embed(title="Commands", color=discord.Color.green())
       # List all commands with descriptions here
       await ctx.send(embed=embed)

   # YOUR COMMANDS HERE (each using embeds + real data)

   if __name__ == "__main__":
       token = os.getenv('DISCORD_TOKEN')
       if not token:
           print("ERROR: DISCORD_TOKEN not found in .env file")
           exit(1)
       try:
           bot.run(token)
       except discord.LoginFailure:
           print("ERROR: Invalid DISCORD_TOKEN")
       except Exception as e:
           print(f"ERROR: {{e}}")
   ```

5. **FILE REQUIREMENTS**:
   - main.py: Complete bot code with all commands
   - requirements.txt: discord.py>=2.3.2, python-dotenv>=1.0.0
   - data.json: Initial data structure (can be empty {{}} or with default schema)

Generate ONLY the JSON object now:"""
    )

    # Invoke prompt with commands, prefix, AND templates
    ai_start = time.time()
    print(f"[GENERATE] 🤖 Calling AI model to generate code...")
    messages = prompt.invoke({
        "description": data.description,
        "discordToken": data.discordToken,
        "prefix": prefix,
        "commands": "\n".join(command_list),
        "templates_context": templates_context  # NEW: Include template guidance
    })
    response = llm.invoke(messages)
    raw_text = response.content.strip()
    ai_elapsed = time.time() - ai_start

    print(f"[GENERATE] ⏱️  AI generated code in {ai_elapsed:.2f}s")
    print(f"[GENERATE] Raw AI response length: {len(raw_text)} chars")

    # DEBUG: Write raw response to file
    debug_file = f"/tmp/cerebras_response_{project_id}.txt"
    with open(debug_file, 'w') as f:
        f.write(raw_text)
    print(f"[GENERATE] 🔍 DEBUG: Raw response saved to {debug_file}")

    # [Rest of the generate function continues with JSON parsing, file writing, etc.]
    # Due to length constraints, I'll add a comment indicating the rest follows the original pattern
    
    # Parse and clean JSON response
    def extract_json_block(text: str) -> str:
        text = re.sub(r"```(?:json)?", "", text)
        text = text.strip()
        text = text.replace("{{discordToken}}", "{discordToken}")
        
        if text.startswith("["):
            print("[GENERATE] Detected array at start, extracting first object...")
            first_brace = text.find("{", 1)
            if first_brace != -1:
                text = text[first_brace:]
        
        if text.startswith("{") and text.endswith("}"):
            return text
        
        start_idx = text.find("{")
        if start_idx == -1:
            return text
        
        brace_count = 0
        end_idx = -1
        in_string = False
        escape_next = False
        
        for i in range(start_idx, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if not in_string:
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break
        
        if end_idx != -1:
            return text[start_idx:end_idx+1].strip()
        return text[start_idx:].strip()

    cleaned_text = extract_json_block(raw_text)

    if not cleaned_text.strip():
        raise HTTPException(status_code=502, detail="Model returned empty response")

    # FIX: Convert Python triple-quoted strings to JSON-escaped strings
    # Cerebras sometimes returns invalid JSON with """ instead of proper escaping
    def fix_triple_quotes(text: str) -> str:
        """Replace Python triple-quote strings with JSON-safe strings"""
        import re

        # Find all """...""" blocks and convert them to proper JSON strings
        def replace_triple_quote(match):
            content = match.group(1)
            # Escape special JSON characters
            content = content.replace('\\', '\\\\')
            content = content.replace('"', '\\"')
            content = content.replace('\n', '\\n')
            content = content.replace('\r', '\\r')
            content = content.replace('\t', '\\t')
            return f'"{content}"'

        # Match """...""" (non-greedy)
        result = re.sub(r'"""(.*?)"""', replace_triple_quote, text, flags=re.DOTALL)
        return result

    # Apply triple-quote fix FIRST
    cleaned_text = fix_triple_quotes(cleaned_text)
    print(f"[GENERATE] After triple-quote fix, length: {len(cleaned_text)}")

    def fix_escape_sequences(text: str) -> str:
        def fix_string(match):
            content = match.group(0)
            fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', content)
            return fixed
        result = re.sub(r'"(?:[^"\\]|\\.)*"', fix_string, text)
        return result

    pre_fixed = fix_escape_sequences(cleaned_text)
    repaired_text = repair_json(pre_fixed)
    
    try:
        plan = json.loads(repaired_text)
    except json.JSONDecodeError as e:
        print(f"[GENERATE] Parse failed: {e}")
        raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {str(e)}")
    
    if isinstance(plan, list):
        if len(plan) > 0 and isinstance(plan[0], dict):
            plan = plan[0]
        else:
            plan = {"summary": "Discord Bot", "features": [], "structure": {}, "files": []}
    
    files: List[Dict[str, str]] = plan.get("files", [])
    
    # Ensure requirements.txt exists
    has_requirements = any(f.get("path") == "requirements.txt" for f in files if isinstance(f, dict))
    if not has_requirements:
        files.append({"path": "requirements.txt", "content": "discord.py>=2.3.2\npython-dotenv>=1.0.0\n"})

    # Add Railway configuration file
    railway_config = {
        "path": "railway.json",
        "content": json.dumps({
            "build": {
                "builder": "NIXPACKS"
            },
            "deploy": {
                "startCommand": "python main.py",
                "restartPolicyType": "ON_FAILURE",
                "restartPolicyMaxRetries": 10
            }
        }, indent=2)
    }
    files.append(railway_config)

    # Add Nixpacks configuration for Python runtime
    nixpacks_config = {
        "path": "nixpacks.toml",
        "content": """[phases.setup]
providers = ["python"]

[phases.install]
cmds = ["pip install -r requirements.txt"]

[start]
cmd = "python main.py"
"""
    }
    files.append(nixpacks_config)
    
    # Write files
    for file_obj in files:
        # Handle both dict and string objects
        if isinstance(file_obj, str):
            continue  # Skip string entries
        if not isinstance(file_obj, dict):
            continue  # Skip non-dict entries

        path = file_obj.get("path")
        content = file_obj.get("content", "").strip()
        print(f"[GENERATE] Processing file: {path}, content length: {len(content)} chars")
        if not path or not isinstance(path, str):
            print(f"[GENERATE] ⚠️  Skipping invalid path: {path}")
            continue
        if not content:
            print(f"[GENERATE] ⚠️  WARNING: {path} has EMPTY content!")
        
        # Replace token placeholders
        for placeholder in ["{discordToken}", "{{discordToken}}", "YOUR_TOKEN_HERE"]:
            if placeholder in content:
                content = content.replace(placeholder, data.discordToken)
        
        # Validate Python files
        if path.endswith('.py'):
            error = validate_python_syntax(content, path)
            if error:
                print(f"[VALIDATE] ❌ Syntax error: {error}")
                fixed_content = fix_python_syntax_with_ai(content, error, path)
                if validate_python_syntax(fixed_content, path) is None:
                    print(f"[FIX] ✅ Auto-fixed syntax errors")
                    content = fixed_content
        
        write_file(project_dir, path, content)
        print(f"[GENERATE] ✅ Wrote file: {path}")
    
    # Create .env file
    env_content = f"DISCORD_TOKEN={data.discordToken}\n"
    write_file(project_dir, ".env", env_content)
    
    # Save project metadata
    if data.user_id:
        bot_name = data.description[:50] + ("..." if len(data.description) > 50 else "")
        save_project_metadata(project_id, data.user_id, bot_name, data.description, data.applicationId)
    
    tree = build_tree(project_dir)
    total_time = time.time() - start_time
    print(f"[GENERATE] ✅ TOTAL generation completed in {total_time:.2f}s")
    print(f"{'='*60}\n")
    
    return {
        "projectId": project_id,
        "summary": plan.get("summary", ""),
        "features": plan.get("features", []),
        "structure": plan.get("structure", {}),
        "tree": tree,
    }

@app.get("/projects")
async def list_projects(user_id: str = Query(..., description="User ID")):
    """List all projects for a user"""
    projects = get_user_projects(user_id)
    return {"projects": projects}

@app.get("/projects/{project_id}/tree")
async def get_project_tree(project_id: str):
    project_dir = get_project_dir(project_id)
    if not os.path.exists(project_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"projectId": project_id, "tree": build_tree(project_dir)}

@app.get("/projects/{project_id}/file")
async def read_project_file(project_id: str, path: str = Query(..., description="Relative file path")):
    project_dir = get_project_dir(project_id)
    content = read_file_from_workspace(project_dir, path)
    return {"projectId": project_id, "path": path, "content": content}

@app.put("/projects/{project_id}/file")
async def write_project_file(project_id: str, body: FileWriteRequest):
    project_dir = get_project_dir(project_id)
    ensure_directory_exists(project_dir)
    write_file(project_dir, body.path, body.content)
    update_project_modified(project_id)
    return {"ok": True}

@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Query(..., description="User ID")):
    """Delete a project and its files"""
    import shutil
    metadata = get_project_metadata(project_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Project not found")
    if metadata.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Stop container
    container_name = f"bot-{project_id}"
    try:
        try:
            subprocess.run(["docker", "stop", "-t", "5", container_name], capture_output=True, timeout=8)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=5)
        subprocess.run(["docker", "rm", container_name], capture_output=True, timeout=10)
    except:
        pass
    
    if project_id in running_containers:
        del running_containers[project_id]
    
    project_dir = get_project_dir(project_id)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)
    
    projects = load_projects()
    if project_id in projects:
        del projects[project_id]
        save_projects(projects)
    
    users = load_users()
    if user_id in users and project_id in users[user_id]["projects"]:
        users[user_id]["projects"].remove(project_id)
        save_users(users)
    
    return {"message": "Project deleted successfully"}

@app.post("/start")
async def start_container(data: ContainerStartRequest):
    """Start a Docker container for the bot project"""
    check_docker_daemon()
    project_id = data.project_id
    project_dir = get_project_dir(project_id)
    
    if not os.path.exists(project_dir):
        raise HTTPException(status_code=404, detail="Project not found")
    
    container_name = f"bot-{project_id}"
    
    # Check if already running
    try:
        inspect_result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True, text=True, timeout=5
        )
        if inspect_result.returncode == 0 and inspect_result.stdout.strip() == "true":
            container_id_result = subprocess.run(
                ["docker", "inspect", "-f", "{{.Id}}", container_name],
                capture_output=True, text=True, timeout=5
            )
            if container_id_result.returncode == 0:
                container_id = container_id_result.stdout.strip()
                running_containers[project_id] = container_id
                return {"status": "already_running", "container_id": container_id}
    except:
        pass
    
    # Clean up existing
    try:
        try:
            subprocess.run(["docker", "stop", "-t", "5", container_name], capture_output=True, timeout=8)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=5)
        subprocess.run(["docker", "rm", container_name], capture_output=True, timeout=10)
    except:
        pass
    
    # Detect main file
    main_file = None
    for filename in ["src/bot.py", "bot.py", "main.py", "src/main.py"]:
        if os.path.exists(os.path.join(project_dir, filename)):
            main_file = filename
            break
    
    if not main_file:
        raise HTTPException(status_code=400, detail="No main bot file found")
    
    # Build Dockerfile
    dockerfile_content = f"""FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
CMD ["python", "-u", "{main_file}"]
"""
    
    with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)
    
    try:
        # Build image
        image_tag = f"discord-bot-{project_id}"
        build_result = subprocess.run(
            ["docker", "build", "-t", image_tag, "."],
            cwd=project_dir, capture_output=True, text=True, timeout=120
        )
        
        if build_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Docker build failed: {build_result.stderr}")
        
        # Read DISCORD_TOKEN from .env file to pass to container
        env_file_path = os.path.join(project_dir, ".env")
        discord_token = None
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as f:
                for line in f:
                    if line.strip().startswith("DISCORD_TOKEN="):
                        discord_token = line.split("=", 1)[1].strip()
                        break

        if not discord_token:
            raise HTTPException(status_code=400, detail="DISCORD_TOKEN not found in .env file")

        # Run container with environment variables for both TOKEN and DISCORD_TOKEN
        # This ensures compatibility with both old and new bot code
        run_result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", container_name,
                "-e", f"DISCORD_TOKEN={discord_token}",
                "-e", f"TOKEN={discord_token}",  # For old bots that use TOKEN
                image_tag
            ],
            capture_output=True, text=True, timeout=10
        )

        if run_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Docker run failed: {run_result.stderr}")

        container_id = run_result.stdout.strip()
        running_containers[project_id] = container_id

        return {"status": "started", "container_id": container_id, "project_id": project_id}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Docker operation timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start container: {str(e)}")

@app.post("/stop")
async def stop_container(data: ContainerStopRequest):
    """Stop a running Docker container"""
    check_docker_daemon()
    project_id = data.project_id
    container_name = f"bot-{project_id}"
    
    try:
        inspect_result = subprocess.run(
            ["docker", "inspect", "-f", "{{.Id}}", container_name],
            capture_output=True, text=True, timeout=5
        )
        
        if inspect_result.returncode != 0:
            raise HTTPException(status_code=404, detail="No running container for this project")
        
        container_id = inspect_result.stdout.strip()
        
        try:
            subprocess.run(["docker", "stop", "-t", "5", container_name], capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", container_name], capture_output=True, text=True, timeout=5)
        subprocess.run(["docker", "rm", container_name], capture_output=True, text=True, timeout=10)
        
        if project_id in running_containers:
            del running_containers[project_id]
        
        return {"status": "stopped", "project_id": project_id, "container_id": container_id}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Docker stop timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop container: {str(e)}")

@app.get("/logs")
async def get_logs(project_id: str = Query(..., description="Project ID")):
    """Get logs from a running Docker container"""
    try:
        check_docker_daemon()
    except HTTPException:
        return {
            "project_id": project_id,
            "logs": "",
            "error": "Docker daemon is not running",
            "status": "docker_not_running"
        }
    
    container_name = f"bot-{project_id}"
    
    try:
        inspect_result = subprocess.run(
            ["docker", "inspect", "-f", "{{.Id}}", container_name],
            capture_output=True, text=True, timeout=5
        )
        
        if inspect_result.returncode != 0:
            return {
                "project_id": project_id,
                "logs": "",
                "error": "No running container for this project",
                "status": "container_not_running"
            }
        
        logs_result = subprocess.run(
            ["docker", "logs", "--tail", "500", container_name],
            capture_output=True, text=True, timeout=10
        )
        
        return {
            "project_id": project_id,
            "logs": logs_result.stdout + logs_result.stderr,
            "status": "success"
        }
    except subprocess.TimeoutExpired:
        return {
            "project_id": project_id,
            "logs": "",
            "error": "Failed to fetch logs (timeout)",
            "status": "error"
        }
    except Exception as e:
        return {
            "project_id": project_id,
            "logs": "",
            "error": f"Failed to fetch logs: {str(e)}",
            "status": "error"
        }

@app.post("/admin/reindex-templates")
async def reindex_templates():
    """Admin endpoint to force re-index templates"""
    try:
        print("[ADMIN] Forcing RAG reindex...")
        rag_service.reinitialize()
        return {"status": "success", "message": "Templates reindexed successfully"}
    except Exception as e:
        print(f"[ADMIN] Reindex failed: {e}")
        raise HTTPException(status_code=500, detail=f"Reindex failed: {str(e)}")

@app.post("/ai-assist")
async def ai_assist(data: AIAssistRequest):
    """AI assistant for code editor - helps with code questions, edits, and suggestions"""
    try:
        project_id = data.project_id
        message = data.message
        project_dir = get_project_dir(project_id)

        if not os.path.exists(project_dir):
            raise HTTPException(status_code=404, detail="Project not found")

        # Use Llama 4 Maverick for comprehensive responses
        llm = get_llm(model="llama-4-maverick-17b-128e-instruct")

        # Build context from conversation history
        conversation_context = ""
        if data.conversation_history:
            for msg in data.conversation_history[-4:]:  # Last 4 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                conversation_context += f"{role.upper()}: {content}\n"

        # Build comprehensive project context including file contents and logs
        project_context = ""
        
        # Get file tree
        if data.file_tree:
            def summarize_tree(nodes, depth=0):
                summary = ""
                for node in nodes:
                    indent = "  " * depth
                    name = node.get("name", "")
                    node_type = node.get("type", "")
                    summary += f"{indent}- {name} ({node_type})\n"
                    if node.get("children"):
                        summary += summarize_tree(node["children"], depth + 1)
                return summary
            file_tree_summary = summarize_tree(data.file_tree)
            project_context += f"PROJECT STRUCTURE:\n{file_tree_summary}\n\n"
        
        # Get actual file contents for key files
        key_files = ["main.py", "bot.py", "requirements.txt", "data.json"]
        for filename in key_files:
            try:
                file_path = os.path.join(project_dir, filename)
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        project_context += f"FILE: {filename}\n```\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n```\n\n"
            except Exception as e:
                project_context += f"FILE: {filename} - Error reading: {str(e)}\n\n"
        
        # Get recent logs if available
        try:
            container_name = f"bot-{project_id}"
            logs_result = subprocess.run(
                ["docker", "logs", "--tail", "50", container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if logs_result.returncode == 0:
                logs = logs_result.stdout + logs_result.stderr
                if logs.strip():
                    project_context += f"RECENT LOGS:\n```\n{logs[-1000:]}{'...' if len(logs) > 1000 else ''}\n```\n\n"
        except:
            pass  # Docker not available or container not running

        prompt = ChatPromptTemplate.from_template(
            """You are a friendly Discord bot coding assistant with conversational intelligence.

{project_context}

CONVERSATION HISTORY:
{conversation}

USER REQUEST:
{message}

CRITICAL: UNDERSTAND USER INTENT FIRST
Before responding, determine what the user ACTUALLY wants:

1. **INFORMATIONAL QUESTIONS** (NO CODE NEEDED):
   - "what command did you add?"
   - "how does this work?"
   - "what does this do?"
   - "explain this feature"
   - "what changed?"

   Response: Just answer their question conversationally. NO CODE BLOCKS.

2. **CODE CHANGE REQUESTS** (CODE NEEDED):
   - "add a feature..."
   - "fix the error..."
   - "change this to..."
   - "implement..."
   - "update the code..."

   Response: Provide COMPLETE file contents in code blocks that will be auto-applied.

RESPONSE RULES:
- If user asks a QUESTION → Answer conversationally, NO code blocks
- If user asks to ADD/FIX/CHANGE → Provide complete code in blocks
- Remember conversation history - don't repeat yourself
- Be concise and friendly
- Only show code when user explicitly wants changes

WHEN PROVIDING CODE (only if user requests changes):
Use these formats:

**For main.py:**
```python
[COMPLETE FILE CONTENTS]
```

**For data.json:**
```json
{{
  "complete": "json content"
}}
```

**For .env:**
```env
DISCORD_TOKEN=value
```

**For requirements.txt:**
```txt
discord.py>=2.3.2
python-dotenv>=1.0.0
```

CONVERSATIONAL EXAMPLES:

User: "what command did you add?"
You: "I added two commands:
- `!addtrackedchannel #channel` - Adds a channel to track for cursed words
- `!removetrackedchannel #channel` - Removes a channel from tracking

These let you control which channels the bot monitors for inappropriate language."

User: "add a ban command"
You: "I'll add a ban command. Here's the updated main.py with the new feature:

```python
[COMPLETE CODE WITH BAN COMMAND]
```

The ban command lets moderators ban users with `!ban @user reason`."

REMEMBER: Answer questions with words, implement changes with code."""
        )

        messages = prompt.invoke({
            "project_context": project_context or "No project context available",
            "conversation": conversation_context or "No previous conversation",
            "message": message
        })

        response = llm.invoke(messages)
        ai_response = response.content.strip()

        # Parse AI response for code changes and actions
        changes_made = []
        needs_restart = False
        # Extract all code blocks from AI response
        code_blocks = re.findall(r'```(\w+)?\n(.*?)\n```', ai_response, re.DOTALL)

        for lang, code_content in code_blocks:
            language_label = (lang or "text").strip().lower()
            code_index = ai_response.find(code_content)
            preceding_text = ai_response[:code_index] if code_index != -1 else ""
            preceding_lower = preceding_text.lower()
            code_lower = code_content.lower()

            # Handle Python files
            if language_label in {"python", "py"}:
                # Determine which file this code belongs to
                target_file = None

                if "main.py" in preceding_lower or "main.py" in code_lower:
                    target_file = "main.py"
                elif "bot.py" in preceding_lower or "bot.py" in code_lower:
                    target_file = "bot.py"
                elif any(indicator in code_lower for indicator in ["bot.run", "discord.ext", "@bot.command"]):
                    # This is likely the main bot file
                    target_file = "main.py" if os.path.exists(os.path.join(project_dir, "main.py")) else "bot.py"

                if target_file:
                    try:
                        file_path = os.path.join(project_dir, target_file)

                        # Validate syntax before writing
                        syntax_error = validate_python_syntax(code_content, target_file)
                        if syntax_error:
                            print(f"[AI-ASSIST] ⚠️ Syntax error in generated code: {syntax_error}")
                            continue

                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(code_content)

                        changes_made.append(f"Updated {target_file}")
                        needs_restart = True
                        print(f"[AI-ASSIST] ✅ Applied changes to {target_file}")
                    except Exception as e:
                        print(f"[AI-ASSIST] ❌ Failed to write {target_file}: {e}")

            # Handle JSON files (data.json)
            elif language_label == "json":
                try:
                    if "data.json" in preceding_lower or "data.json" in code_lower:
                        json_file = os.path.join(project_dir, "data.json")
                        # Validate JSON before writing
                        json.loads(code_content)  # This will raise if invalid
                        with open(json_file, 'w', encoding='utf-8') as f:
                            f.write(code_content)
                        changes_made.append("Updated data.json")
                        print(f"[AI-ASSIST] ✅ Applied changes to data.json")
                except json.JSONDecodeError as e:
                    print(f"[AI-ASSIST] ⚠️ Invalid JSON: {e}")
                except Exception as e:
                    print(f"[AI-ASSIST] ❌ Failed to write data.json: {e}")

            # Handle .env files
            elif language_label in {"makefile", "env", "dotenv"} or "discord_token" in code_lower:
                try:
                    env_file = os.path.join(project_dir, ".env")
                    with open(env_file, 'w', encoding='utf-8') as f:
                        f.write(code_content)
                    changes_made.append("Updated .env file")
                    needs_restart = True
                    print(f"[AI-ASSIST] ✅ Applied changes to .env")
                except Exception as e:
                    print(f"[AI-ASSIST] ❌ Failed to write .env: {e}")

            # Handle requirements.txt
            elif language_label in {"txt", "text"}:
                try:
                    if "requirements.txt" in preceding_lower or "requirements.txt" in code_lower:
                        req_file = os.path.join(project_dir, "requirements.txt")
                        with open(req_file, 'w', encoding='utf-8') as f:
                            f.write(code_content)
                        changes_made.append("Updated requirements.txt")
                        needs_restart = True
                        print(f"[AI-ASSIST] ✅ Applied changes to requirements.txt")
                except Exception as e:
                    print(f"[AI-ASSIST] ❌ Failed to write requirements.txt: {e}")

        # Auto-restart container if changes were made
        if needs_restart and changes_made:
            try:
                container_name = f"bot-{project_id}"

                # Stop existing container - use kill for faster, guaranteed stop
                print(f"[AI-ASSIST] Stopping container {container_name}...")
                try:
                    # Try graceful stop first with shorter timeout
                    subprocess.run(["docker", "stop", "-t", "5", container_name], capture_output=True, timeout=8)
                except subprocess.TimeoutExpired:
                    # Force kill if graceful stop fails
                    print(f"[AI-ASSIST] Graceful stop timed out, force killing...")
                    subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=5)

                # Remove old container
                rm_result = subprocess.run(["docker", "rm", container_name], capture_output=True, timeout=10)
                print(f"[AI-ASSIST] Removed old container (exit code: {rm_result.returncode})")

                # Rebuild and restart
                print(f"[AI-ASSIST] Rebuilding container...")

                # Find main file (same order as /start endpoint)
                main_file = None
                for filename in ["src/bot.py", "bot.py", "main.py", "src/main.py"]:
                    if os.path.exists(os.path.join(project_dir, filename)):
                        main_file = filename
                        break

                if main_file:
                    # Create Dockerfile
                    dockerfile_content = f"""FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
CMD ["python", "-u", "{main_file}"]
"""
                    with open(os.path.join(project_dir, "Dockerfile"), "w") as f:
                        f.write(dockerfile_content)

                    # Build image with --no-cache to ensure fresh build after code changes
                    image_tag = f"discord-bot-{project_id}"
                    print(f"[AI-ASSIST] Building image {image_tag} with --no-cache...")
                    build_result = subprocess.run(
                        ["docker", "build", "--no-cache", "-t", image_tag, "."],
                        cwd=project_dir,
                        capture_output=True,
                        text=True,
                        timeout=120
                    )

                    if build_result.returncode == 0:
                        print(f"[AI-ASSIST] ✅ Build successful, starting container...")

                        # Read DISCORD_TOKEN from .env file to pass to container
                        env_file_path = os.path.join(project_dir, ".env")
                        discord_token = None
                        if os.path.exists(env_file_path):
                            with open(env_file_path, 'r') as f:
                                for line in f:
                                    if line.strip().startswith("DISCORD_TOKEN="):
                                        discord_token = line.split("=", 1)[1].strip()
                                        break

                        if not discord_token:
                            changes_made.append("❌ DISCORD_TOKEN not found in .env")
                            print(f"[AI-ASSIST] ❌ No DISCORD_TOKEN in .env file")
                        else:
                            # Run container with environment variables
                            run_result = subprocess.run(
                                [
                                    "docker", "run", "-d",
                                    "--name", container_name,
                                    "-e", f"DISCORD_TOKEN={discord_token}",
                                    "-e", f"TOKEN={discord_token}",  # For old bots
                                    image_tag
                                ],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )

                            if run_result.returncode == 0:
                                container_id = run_result.stdout.strip()
                                running_containers[project_id] = container_id
                                changes_made.append("✅ Container restarted successfully")
                                print(f"[AI-ASSIST] ✅ Container restarted: {container_id[:12]}")
                            else:
                                error_msg = run_result.stderr.strip()
                                changes_made.append(f"❌ Failed to start: {error_msg[:100]}")
                                print(f"[AI-ASSIST] ❌ Failed to start container: {error_msg}")
                    else:
                        error_msg = build_result.stderr.strip()
                        changes_made.append(f"❌ Build failed: {error_msg[:100]}")
                        print(f"[AI-ASSIST] ❌ Docker build failed:\n{error_msg}")
                else:
                    changes_made.append("❌ Could not find main bot file")
                    print(f"[AI-ASSIST] ❌ No main file found in {project_dir}")
            except Exception as e:
                error_msg = str(e)
                changes_made.append(f"❌ Restart error: {error_msg[:100]}")
                print(f"[AI-ASSIST] ❌ Restart error: {error_msg}")

        # Update project modified timestamp
        if changes_made:
            update_project_modified(project_id)

        if changes_made:
            formatted_changes = "\n".join(f"- {change}" for change in changes_made)
            display_response = f"I updated the project:\n{formatted_changes}"
        else:
            stripped = strip_code_blocks(ai_response)
            display_response = stripped if stripped else "I didn't apply any file edits. Let me know what you'd like me to change."

        return {
            "response": display_response,
            "raw_response": ai_response,
            "changes_applied": len(changes_made) > 0,
            "auto_restarted": needs_restart and any("restarted successfully" in c for c in changes_made),
            "summary": f"Applied {len(changes_made)} changes" if changes_made else None,
            "changes": changes_made
        }

    except Exception as e:
        print(f"[AI-ASSIST] Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI assist failed: {str(e)}")

@app.post("/fix-syntax-errors")
async def fix_syntax_errors(data: ContainerStartRequest):
    """Check bot logs for syntax errors and auto-fix them"""
    try:
        project_id = data.project_id
        project_dir = get_project_dir(project_id)

        if not os.path.exists(project_dir):
            raise HTTPException(status_code=404, detail="Project not found")

        # Get container logs
        container_name = f"bot-{project_id}"
        try:
            logs_result = subprocess.run(
                ["docker", "logs", container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            logs = logs_result.stdout + logs_result.stderr
        except:
            return {"status": "no_logs", "message": "Could not retrieve logs"}

        # Check for syntax errors in logs
        syntax_error_patterns = [
            r"SyntaxError: (.+)",
            r'File "(.+)", line (\d+)',
            r"unterminated string literal",
            r"invalid syntax"
        ]

        has_syntax_error = any(re.search(pattern, logs, re.IGNORECASE) for pattern in syntax_error_patterns)

        if not has_syntax_error:
            return {"status": "no_errors", "message": "No syntax errors detected"}

        # Extract error details
        file_match = re.search(r'File "([^"]+)", line (\d+)', logs)
        error_match = re.search(r"SyntaxError: (.+)", logs)

        if not file_match:
            return {"status": "no_fix", "message": "Could not determine error location"}

        error_file = file_match.group(1)
        error_line = int(file_match.group(2))
        error_msg = error_match.group(1) if error_match else "Syntax error"

        # Read the problematic file
        file_basename = os.path.basename(error_file)
        try:
            file_content = read_file_from_workspace(project_dir, file_basename)
        except:
            return {"status": "file_not_found", "message": f"Could not read {file_basename}"}

        # Use AI to fix the syntax error
        fixed_content = fix_python_syntax_with_ai(file_content, error_msg, file_basename)

        # Validate the fix
        if validate_python_syntax(fixed_content, file_basename) is None:
            # Save the fixed file
            write_file(project_dir, file_basename, fixed_content)
            return {
                "status": "fixed",
                "file": file_basename,
                "line": error_line,
                "error": error_msg,
                "message": f"Fixed syntax error in {file_basename}"
            }
        else:
            return {"status": "fix_failed", "message": "Auto-fix did not resolve the error"}

    except Exception as e:
        print(f"[FIX-SYNTAX] Error: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/export-project-zip")
async def export_project_zip(data: RailwayDeployRequest):
    """Export project as a ZIP file for Railway deployment"""
    import zipfile
    import io

    try:
        project_id = data.project_id
        project_dir = get_project_dir(project_id)

        if not os.path.exists(project_dir):
            raise HTTPException(status_code=404, detail="Project not found")

        print(f"[EXPORT] Creating ZIP for project {project_id}...")

        # Create ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for root, dirs, files in os.walk(project_dir):
                for file in files:
                    if file == "Dockerfile":
                        continue  # Skip Docker-specific files
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, project_dir)
                    zip_file.write(file_path, arcname)

        zip_buffer.seek(0)

        # Return ZIP file
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=discord-bot-{project_id}.zip"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"[EXPORT] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

@app.get("/railway-deploy-url/{project_id}")
async def get_railway_deploy_url(project_id: str):
    """Generate deployment instructions for the project"""
    try:
        project_dir = get_project_dir(project_id)

        if not os.path.exists(project_dir):
            raise HTTPException(status_code=404, detail="Project not found")

        metadata = get_project_metadata(project_id)
        project_name = metadata.get("name", f"bot-{project_id}") if metadata else f"bot-{project_id}"

        # Read DISCORD_TOKEN from .env for instructions
        env_file_path = os.path.join(project_dir, ".env")
        discord_token = ""
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as f:
                for line in f:
                    if line.startswith("DISCORD_TOKEN="):
                        discord_token = line.split("=", 1)[1].strip()
                        break

        return {
            "project_name": project_name,
            "discord_token": discord_token,
            "instructions": [
                "1. Download your bot files as a ZIP",
                "2. Deploy to your preferred hosting service",
                "3. Add DISCORD_TOKEN as an environment variable",
                "4. Your bot will run 24/7!"
            ]
        }

    except Exception as e:
        print(f"[DEPLOY] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate deployment info: {str(e)}")
