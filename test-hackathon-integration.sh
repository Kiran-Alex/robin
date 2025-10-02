#!/bin/bash

echo "🧪 Testing FutureStack Hackathon Integration"
echo "==========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test 1: Check Cerebras API
echo -e "${YELLOW}Test 1: Cerebras API Configuration${NC}"
if [ -f .env ] && grep -q "CEREBRAS_API_KEY" .env; then
    echo -e "${GREEN}✅ Cerebras API key found in .env${NC}"
else
    echo -e "${RED}❌ Cerebras API key not configured${NC}"
    echo "   Add CEREBRAS_API_KEY to .env file"
fi
echo ""

# Test 2: Check Docker MCP Gateway
echo -e "${YELLOW}Test 2: Docker MCP Gateway${NC}"
if command -v docker &> /dev/null; then
    if docker mcp --version &> /dev/null 2>&1; then
        echo -e "${GREEN}✅ Docker MCP Gateway installed${NC}"
    else
        echo -e "${RED}❌ Docker MCP Gateway not installed${NC}"
        echo "   Run: ./setup-mcp.sh"
    fi
else
    echo -e "${RED}❌ Docker not installed${NC}"
fi
echo ""

# Test 3: Check Python dependencies
echo -e "${YELLOW}Test 3: Python Dependencies${NC}"
source venv/bin/activate 2>/dev/null
if python -c "import langchain_cerebras" 2>/dev/null; then
    echo -e "${GREEN}✅ langchain-cerebras installed${NC}"
else
    echo -e "${RED}❌ langchain-cerebras not installed${NC}"
fi

if python -c "import langchain_ollama" 2>/dev/null; then
    echo -e "${GREEN}✅ langchain-ollama installed${NC}"
else
    echo -e "${RED}❌ langchain-ollama not installed${NC}"
fi

if python -c "import langchain_community" 2>/dev/null; then
    echo -e "${GREEN}✅ langchain-community installed${NC}"
else
    echo -e "${RED}❌ langchain-community not installed${NC}"
fi
echo ""

# Test 4: Check backend MCP integration
echo -e "${YELLOW}Test 4: Backend MCP Integration${NC}"
if grep -q "analyze_mcp_servers_needed" backend/main.py; then
    echo -e "${GREEN}✅ MCP server analysis function found${NC}"
else
    echo -e "${RED}❌ MCP server analysis not implemented${NC}"
fi

if grep -q "get_llama_llm" backend/main.py; then
    echo -e "${GREEN}✅ Llama LLM integration found${NC}"
else
    echo -e "${RED}❌ Llama LLM not implemented${NC}"
fi
echo ""

# Test 5: Check frontend updates
echo -e "${YELLOW}Test 5: Frontend MCP Display${NC}"
if grep -q "mcp_capabilities" app/page.tsx; then
    echo -e "${GREEN}✅ Frontend MCP capabilities display found${NC}"
else
    echo -e "${RED}❌ Frontend MCP display not implemented${NC}"
fi
echo ""

# Test 6: MCP Server Configuration
echo -e "${YELLOW}Test 6: MCP Server Configuration${NC}"
if grep -q "MCP_SERVERS_CONFIG" backend/main.py; then
    echo -e "${GREEN}✅ MCP server configuration found${NC}"
    echo "   Servers: DuckDuckGo, Fetch, GitHub"
else
    echo -e "${RED}❌ MCP server configuration not found${NC}"
fi
echo ""

# Summary
echo "==========================================="
echo -e "${YELLOW}🏆 Hackathon Technologies Status:${NC}"
echo ""
echo "⚡ Cerebras API:"
echo "   - Code generation with Qwen 3 Coder 480B"
echo "   - Command planning with Llama 4 Scout"
echo ""
echo "🦙 Meta Llama:"
echo "   - Creative content via Langchain Ollama"
echo "   - Bot personality generation"
echo ""
echo "🐳 Docker MCP Gateway:"
echo "   - DuckDuckGo: Web search"
echo "   - Fetch: Content fetching"
echo "   - GitHub: Repository integration"
echo ""
echo -e "${GREEN}Ready for FutureStack GenAI Hackathon! 🚀${NC}"


