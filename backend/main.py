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
from backend.rag_service import get_rag_service

# Ensure env var is present but do not crash app on missing key
_cerebras_api_key = os.getenv("CEREBRAS_API_KEY")
if _cerebras_api_key:
    os.environ["CEREBRAS_API_KEY"] = _cerebras_api_key

def get_llm(model: str = "llama-4-scout-17b-16e-instruct", timeout: int = 30) -> ChatCerebras:
    """
    Lazily initialize the LLM so the app can start even if the key is missing
    Default model: llama-4-scout-17b-16e-instruct (newest Llama 4 model, 2600 tokens/s)
    Alternative models: llama-3.3-70b (stable, fast), llama-4-maverick-17b-128e-instruct (largest, preview)
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
        llm = get_llm()
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
        llm = get_llm(model="llama-4-scout-17b-16e-instruct", timeout=15)  # 15s timeout
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

    llm = get_llm(model="qwen-3-coder-480b")  # Qwen 3 Coder 480B - best for code generation
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
        subprocess.run(
            ["docker", "stop", container_name],
            capture_output=True,
            timeout=10
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
        """You are an expert Discord bot developer. Build a FULLY FUNCTIONAL bot with complete game mechanics.

USER REQUEST: {description}

COMMANDS TO IMPLEMENT:
{commands}

PREFIX: {prefix}

===== REFERENCE TEMPLATES (USE THESE PATTERNS) =====
{templates_context}

IMPORTANT: The templates above are REFERENCE EXAMPLES showing proven Discord.py patterns.
- DO NOT copy them directly
- ADAPT the patterns to fit the user's specific request
- Use similar structure, error handling, and data persistence approaches
- Implement the user's requested features, not the template features
===== END TEMPLATES =====

STEP 1: ANALYZE THE COMMANDS AND INTERLINK THEM
For each command, ask yourself:
- What data needs to be stored? (user stats, items, relationships, progress, etc.)
- What logic is required? (calculations, random generation, validation, matching, etc.)
- What user interactions are needed? (mention other users, input validation, confirmations, etc.)
- What edge cases exist? (user not found, insufficient resources, already exists, etc.)
- CRITICAL: How does this command interlink with others? Define prerequisites and state management.

STEP 2: DESIGN THE DATA MODEL WITH STATE MANAGEMENT
Think about what data structures you need - use the template patterns as a guide for data persistence.

STEP 3: IMPLEMENT WORKING FUNCTIONALITY WITH INTERLINKING
For EVERY command, write working code based on template patterns where applicable.

CRITICAL ANTI-PLACEHOLDER RULES:
❌ NEVER write responses like: "Profile viewed!", "Rank checked!"
✅ ALWAYS show actual data from the data structures

STEP 4: STRUCTURE THE CODE
Organize into appropriate files (use template structure as reference):
- Main bot file with all commands
- requirements.txt (REQUIRED: must include discord.py>=2.3.2 and python-dotenv>=1.0.0)
- Data files (JSON) for persistence

REQUIREMENTS:
- Use discord.Intents.default() + message_content = True
- IMPORTANT: Always set help_command=None when creating the bot
- Create a custom @bot.command() async def help(ctx) function
- Use {discordToken} in .env
- Implement REAL functionality, not stubs
- Follow template patterns for error handling and data persistence

CRITICAL JSON FORMAT REQUIREMENTS:
Return a SINGLE JSON OBJECT (not an array):
{{
  "summary": "Bot description",
  "features": ["list", "of", "commands"],
  "structure": {{"files": ["main.py", "requirements.txt"], "description": "Organization"}},
  "files": [
    {{"path": "main.py", "content": "COMPLETE BOT CODE"}},
    {{"path": "requirements.txt", "content": "discord.py>=2.3.2\\npython-dotenv>=1.0.0"}},
    {{"path": "data.json", "content": "{{\\"users\\": {{}}}}"}}
  ]
}}

YOUR RESPONSE MUST START WITH {{ NOT [

Return ONLY the JSON object:"""
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
    
    # Write files
    for file_obj in files:
        path = file_obj.get("path")
        content = file_obj.get("content", "").strip()
        if not path or not isinstance(path, str):
            continue
        
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
        subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
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
        subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=10)
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
        
        # Run container
        run_result = subprocess.run(
            ["docker", "run", "-d", "--name", container_name, image_tag],
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
        
        subprocess.run(["docker", "stop", container_name], capture_output=True, text=True, timeout=30)
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

        # Use Llama 4 Scout for fast responses
        llm = get_llm(model="llama-4-scout-17b-16e-instruct")

        # Build context from conversation history
        conversation_context = ""
        if data.conversation_history:
            for msg in data.conversation_history[-4:]:  # Last 4 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                conversation_context += f"{role.upper()}: {content}\n"

        # Build file tree context
        file_tree_summary = ""
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

        prompt = ChatPromptTemplate.from_template(
            """You are an AI coding assistant helping with a Discord bot project.

PROJECT STRUCTURE:
{file_tree}

CONVERSATION HISTORY:
{conversation}

USER REQUEST:
{message}

INSTRUCTIONS:
1. If the user asks about the project, explain based on the file structure
2. If they request code changes, provide clear instructions or code snippets
3. If they ask to add features, suggest specific file changes
4. Be concise and helpful
5. If you suggest code changes, indicate which file to modify

Respond naturally and helpfully:"""
        )

        messages = prompt.invoke({
            "file_tree": file_tree_summary or "No file tree available",
            "conversation": conversation_context or "No previous conversation",
            "message": message
        })

        response = llm.invoke(messages)
        ai_response = response.content.strip()

        # Determine if changes or restart needed (simple heuristics)
        needs_changes = any(keyword in message.lower() for keyword in ["add", "create", "modify", "change", "fix", "update", "edit"])
        needs_restart = any(keyword in message.lower() for keyword in ["add command", "new command", "restart", "reload"])

        return {
            "response": ai_response,
            "needs_changes": needs_changes,
            "needs_restart": needs_restart,
            "summary": None
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
