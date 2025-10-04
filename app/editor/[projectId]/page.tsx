"use client"

import { useState, useEffect,useRef } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Bot, RefreshCw, Rocket, ExternalLink, FileText, Folder, File, ChevronRight, ChevronDown, Send, Play, Square, Terminal, AlertCircle, Train } from "lucide-react"
import { useRouter } from "next/navigation"
import { Textarea } from "@/components/ui/textarea"
import Editor from "@monaco-editor/react"
import { triggerConfetti } from "@/components/magicui/confetti"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8001"

interface FileNode {
  name: string
  type: "file" | "folder"
  children?: FileNode[]
  content?: string
}

interface BackendNode {
  name: string
  path: string
  type: "file" | "dir"
  children?: BackendNode[]
}

interface ChatMessage {
  id: string
  role: "user" | "ai"
  content: string
}

interface LogsResponse {
  project_id: string
  logs: string
  status?: "success" | "docker_not_running" | "container_not_running" | "error"
  error?: string
}

const mockFileTree: FileNode[] = []

export default function EditorPage({ params }: { params: { projectId: string } }) {
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null)
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null)
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(["src", "src/commands", "src/events"]))
  const [isDeploying, setIsDeploying] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [railwayUrl, setRailwayUrl] = useState<string | null>(null)
  const [deploymentStatus, setDeploymentStatus] = useState<"idle" | "deploying" | "success" | "error">("idle")
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "ai",
      content: "Hi! I'm your coding assistant. Ask me about this project, request file edits, or generate snippets."
    }
  ])
  const [chatInput, setChatInput] = useState("")
  const [contentsByPath, setContentsByPath] = useState<Record<string, string>>({})
  const [tree, setTree] = useState<BackendNode[]>([])
  const [botRunning, setBotRunning] = useState(false)
  const [botLogs, setBotLogs] = useState("")
  const [isStarting, setIsStarting] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const [dockerStatus, setDockerStatus] = useState<"running" | "not_running" | "unknown">("unknown")
  const [applicationId, setApplicationId] = useState<string>("")
  const [isAiThinking, setIsAiThinking] = useState(false)
  const [confettiShown, setConfettiShown] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const router = useRouter()

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  useEffect(() => {
    const loadTree = async () => {
      const startTime = performance.now()
      try {
        const res = await fetch(`${BACKEND_URL}/projects/${params.projectId}/tree`)
        if (!res.ok) throw new Error("Failed to fetch project tree")
        const data = await res.json()
        setTree(data.tree || [])

        const elapsed = performance.now() - startTime
        console.log(`Tree loaded in ${elapsed.toFixed(0)}ms`)

        // Auto-load main bot file after tree loads
        const mainFiles = ["main.py", "bot.py", "src/bot.py", "src/main.py"]
        for (const fileName of mainFiles) {
          const fileNode = findFileInTree(data.tree || [], fileName)
          if (fileNode) {
            console.log(`Auto-loading ${fileName}...`)
            await loadFileContent(fileNode.path)
            setSelectedFilePath(fileNode.path)
            break
          }
        }

        // Try to extract application ID and autoStart flag from URL params or localStorage
        const urlParams = new URLSearchParams(window.location.search)
        const appId = urlParams.get('applicationId') || localStorage.getItem(`bot_${params.projectId}_appId`) || ""
        const shouldAutoStart = urlParams.get('autoStart') === 'true'
        setApplicationId(appId)

        // Auto-start bot ONLY after tree and files are loaded
        if (shouldAutoStart) {
          console.log("Auto-start flag detected, starting bot after files loaded...")
          setTimeout(() => {
            handleStartBot()
          }, 1000)  // Short delay after files are loaded
        }
      } catch (e) {
        console.error(e)
      }
    }
    loadTree()

    // Check bot and Docker status
    const checkStatus = async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/logs?project_id=${params.projectId}`)
        if (!res.ok) {
          setDockerStatus("not_running")
          return
        }
        const data: LogsResponse = await res.json()
        if (data.status === "success") {
          setBotRunning(true)
          setBotLogs(data.logs || "")
        } else if (data.status === "docker_not_running") {
          setDockerStatus("not_running")
        } else {
          setBotRunning(false)
          setDockerStatus("running") // Docker ok, but container not
        }
      } catch (e) {
        setDockerStatus("not_running")
        console.error(e)
      }
    }
    checkStatus()

    // Cleanup: Stop container ONLY when component unmounts (user navigates away)
    return () => {
      // This only runs when navigating to a different page/route
      console.log("Editor unmounting: stopping bot container...")
      fetch(`${BACKEND_URL}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: params.projectId })
      }).catch(err => console.warn("Failed to stop container on cleanup:", err))
    }
  }, [params.projectId])  // Only depend on projectId, not botRunning

  const findFileInTree = (nodes: BackendNode[], targetName: string): BackendNode | null => {
    for (const node of nodes) {
      if (node.type === "file" && (node.name === targetName || node.path === targetName)) {
        return node
      }
      if (node.type === "dir" && node.children) {
        const found = findFileInTree(node.children, targetName)
        if (found) return found
      }
    }
    return null
  }

  const loadFileContent = async (path: string) => {
    try {
      const content = await readFileFromBackend(path)
      setContentsByPath((prev) => ({ ...prev, [path]: content }))
      return content
    } catch (e) {
      console.error(`Failed to load ${path}:`, e)
      return null
    }
  }

  const readFileFromBackend = async (path: string) => {
    const res = await fetch(`${BACKEND_URL}/projects/${params.projectId}/file?path=${encodeURIComponent(path)}`)
    if (!res.ok) throw new Error("Failed to fetch file")
    const data = await res.json()
    return data.content as string
  }

  const writeFileToBackend = async (path: string, content: string) => {
    const res = await fetch(`${BACKEND_URL}/projects/${params.projectId}/file`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content })
    })
    if (!res.ok) throw new Error("Failed to save file")
  }

  const toggleFolder = (path: string) => {
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(path)) {
      newExpanded.delete(path)
    } else {
      newExpanded.add(path)
    }
    setExpandedFolders(newExpanded)
  }

  const renderBackendTree = (nodes: BackendNode[], pathPrefix = "") => {
    return nodes.map((node) => {
      const currentPath = node.path || (pathPrefix ? `${pathPrefix}/${node.name}` : node.name)

      if (node.type === "dir") {
        const isExpanded = expandedFolders.has(currentPath)
        return (
          <div key={currentPath}>
            <div
              className="flex items-center gap-1 px-2 py-1 text-sm hover:bg-accent rounded cursor-pointer"
              onClick={() => toggleFolder(currentPath)}
            >
              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              <Folder className="h-4 w-4 text-primary" />
              <span>{node.name}</span>
            </div>
            {isExpanded && node.children && <div className="ml-4">{renderBackendTree(node.children, currentPath)}</div>}
          </div>
        )
      } else {
        return (
          <div
            key={currentPath}
            className={`flex items-center gap-1 px-2 py-1 text-sm hover:bg-accent rounded cursor-pointer ml-5 ${
              selectedFilePath === currentPath ? "bg-accent" : ""
            }`}
            onClick={async () => {
              setSelectedFilePath(currentPath)
              try {
                const content = await readFileFromBackend(currentPath)
                setContentsByPath((prev) => ({ ...prev, [currentPath]: content }))
              } catch (e) {
                console.error(e)
              }
            }}
          >
            <File className="h-4 w-4 text-muted-foreground" />
            <span>{node.name}</span>
          </div>
        )
      }
    })
  }

  const handleStartBot = async () => {
    if (dockerStatus === "not_running") {
      alert("Docker daemon is not running. Please start Docker Desktop and try again.")
      return
    }
    setIsStarting(true)
    try {
      const res = await fetch(`${BACKEND_URL}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: params.projectId })
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || "Failed to start bot")
      }
      const data = await res.json()
      setBotRunning(true)
      setDockerStatus("running")
      setShowLogs(true)

      // Fetch logs immediately after starting
      await fetchLogs()

      // Wait 3 seconds then check for syntax errors (only on first start, not recursively)
      const isFirstStart = !sessionStorage.getItem(`bot_${params.projectId}_started`)
      if (isFirstStart) {
        sessionStorage.setItem(`bot_${params.projectId}_started`, 'true')

        setTimeout(async () => {
          try {
            const fixRes = await fetch(`${BACKEND_URL}/fix-syntax-errors`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ project_id: params.projectId })
            })

            if (fixRes.ok) {
              const fixData = await fixRes.json()
              if (fixData.status === "fixed") {
                // Show message
                const aiMsg: ChatMessage = {
                  id: `${Date.now()}-fix`,
                  role: "ai",
                  content: `🔧 Detected and fixed syntax error in ${fixData.file} at line ${fixData.line}. Please restart the bot manually to apply changes.`
                }
                setMessages((prev) => [...prev, aiMsg])

                // Don't auto-restart to avoid infinite loop - let user restart manually
              }
            }
          } catch (err) {
            console.error("Error checking for syntax errors:", err)
          }
        }, 3000)
      }
    } catch (e: any) {
      console.error(e)
      alert(e.message || "Failed to start bot")
    } finally {
      setIsStarting(false)
    }
  }

  const handleStopBot = async () => {
    setIsStopping(true)
    try {
      const res = await fetch(`${BACKEND_URL}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: params.projectId })
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || "Failed to stop bot")
      }
      setBotRunning(false)
      setBotLogs("")
      setConfettiShown(false)  // Reset confetti state when bot stops
      sessionStorage.removeItem(`confetti_${params.projectId}`)  // Clear sessionStorage so confetti can trigger again
    } catch (e: any) {
      console.error(e)
      alert(e.message || "Failed to stop bot")
    } finally {
      setIsStopping(false)
    }
  }

  const fetchLogs = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/logs?project_id=${params.projectId}`)
      if (!res.ok) return
      const data: LogsResponse = await res.json()
      if (data.status === "success") {
        const logs = data.logs || ""
        setBotLogs(logs)

        // Check if bot successfully logged in and confetti hasn't been shown yet
        const confettiKey = `confetti_${params.projectId}`
        const hasShownConfetti = sessionStorage.getItem(confettiKey)

        if (!hasShownConfetti && (logs.includes("Bot logged in as:") || logs.includes("Bot is online and ready!"))) {
          triggerConfetti({ particleCount: 150, spread: 90 })
          sessionStorage.setItem(confettiKey, 'true')
          setConfettiShown(true)
        }
      } else if (data.status === "docker_not_running") {
        setDockerStatus("not_running")
        setBotLogs("")
      } else if (data.status === "container_not_running") {
        setBotRunning(false)
        setBotLogs("")
      }
    } catch (e) {
      console.error("Failed to fetch logs:", e)
    }
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      const res = await fetch(`${BACKEND_URL}/projects/${params.projectId}/tree`)
      if (res.ok) {
        const data = await res.json()
        setTree(data.tree || [])
      }
      if (botRunning || dockerStatus === "running") {
        await fetchLogs()
      }
    } catch (e) {
      console.error(e)
    } finally {
      setIsRefreshing(false)
    }
  }

  const handleDeployToRailway = async () => {
    try {
      // Step 1: Download the project ZIP
      const downloadUrl = `${BACKEND_URL}/export-project-zip`
      const downloadRes = await fetch(downloadUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: params.projectId })
      })

      if (!downloadRes.ok) {
        throw new Error("Failed to prepare project for download")
      }

      // Trigger ZIP download
      const blob = await downloadRes.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `discord-bot-${params.projectId}.zip`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)

      // Step 2: Get Railway deployment info
      const infoRes = await fetch(`${BACKEND_URL}/railway-deploy-url/${params.projectId}`)
      if (!infoRes.ok) {
        throw new Error("Failed to get Railway info")
      }

      const info = await infoRes.json()

      // Step 3: Show instructions in chat
      const instructionsMsg: ChatMessage = {
        id: `${Date.now()}-railway-instructions`,
        role: "ai",
        content: `📦 Project downloaded! Now let's deploy to Railway:\n\n${info.instructions.join('\n')}\n\n⚠️ Important: When Railway asks for environment variables, add:\nDISCORD_TOKEN = ${info.discord_token}\n\nClick "Open Railway" below to start deployment.`
      }
      setMessages((prev) => [...prev, instructionsMsg])

      // Step 4: Open Railway in new tab
      setRailwayUrl(info.railway_url)
      window.open(info.railway_url, '_blank')

      setDeploymentStatus("success")

    } catch (e: any) {
      console.error(e)
      setDeploymentStatus("error")

      const errorMsg: ChatMessage = {
        id: `${Date.now()}-railway-error`,
        role: "ai",
        content: `❌ Failed to prepare Railway deployment: ${e.message}`
      }
      setMessages((prev) => [...prev, errorMsg])
    }
  }

  // Auto-refresh logs when bot is running and Docker is ok
  useEffect(() => {
    if (!botRunning || dockerStatus !== "running") return
    const interval = setInterval(fetchLogs, 3000)
    return () => clearInterval(interval)
  }, [botRunning, params.projectId, dockerStatus])

  const sendMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || isAiThinking) return  // Don't send if AI is thinking

    const userMsg: ChatMessage = { id: `${Date.now()}-u`, role: "user", content: trimmed }
    setMessages((prev) => [...prev, userMsg])
    setChatInput("")
    setIsAiThinking(true)

    // Add "thinking" message
    const thinkingId = `${Date.now()}-thinking`
    const thinkingMsg: ChatMessage = {
      id: thinkingId,
      role: "ai",
      content: "🤔 Thinking..."
    }
    setMessages((prev) => [...prev, thinkingMsg])

    try {
      // Call the AI backend with conversation history
      const res = await fetch(`${BACKEND_URL}/ai-assist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: params.projectId,
          message: trimmed,
          file_tree: tree,
          conversation_history: messages.slice(-6)  // Send last 6 messages for context
        })
      })

      if (!res.ok) throw new Error("AI request failed")

      const data = await res.json()

      // Remove "thinking" message
      setMessages((prev) => prev.filter(m => m.id !== thinkingId))

      // Add AI response
      const aiMsg: ChatMessage = {
        id: `${Date.now()}-a`,
        role: "ai",
        content: data.response || "I've processed your request."
      }
      setMessages((prev) => [...prev, aiMsg])

      // If changes were made, refresh the tree
      if (data.changes_applied) {
        await handleRefresh()

        // Show summary if available
        if (data.summary) {
          const summaryMsg: ChatMessage = {
            id: `${Date.now()}-summary`,
            role: "ai",
            content: `✅ ${data.summary}`
          }
          setMessages((prev) => [...prev, summaryMsg])
        }

        // Show specific changes made
        if (data.changes && data.changes.length > 0) {
          const changesMsg: ChatMessage = {
            id: `${Date.now()}-changes`,
            role: "ai",
            content: `🔧 Changes applied:\n${data.changes.map((c: string) => `• ${c}`).join('\n')}`
          }
          setMessages((prev) => [...prev, changesMsg])
        }

        // If auto-restarted, show restart status
        if (data.auto_restarted) {
          const restartMsg: ChatMessage = {
            id: `${Date.now()}-restart`,
            role: "ai",
            content: "✅ Bot automatically restarted with new changes!"
          }
          setMessages((prev) => [...prev, restartMsg])

          // Refresh bot status and logs
          setBotRunning(true)
          await new Promise(resolve => setTimeout(resolve, 1500))
          await fetchLogs()
        }
      }
    } catch (e) {
      console.error(e)
      // Remove "thinking" message
      setMessages((prev) => prev.filter(m => m.id !== thinkingId))
      const errorMsg: ChatMessage = {
        id: `${Date.now()}-error`,
        role: "ai",
        content: "Sorry, I encountered an error processing your request. Please try again."
      }
      setMessages((prev) => [...prev, errorMsg])
    } finally {
      setIsAiThinking(false)
    }
  }

  const onSubmitChat = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(chatInput)
  }

  const renderDockerStatus = () => {
    if (dockerStatus === "not_running") {
      return (
        <div className="flex items-center gap-2 p-2 bg-destructive/10 border border-destructive/20 rounded-md text-destructive text-sm">
          <AlertCircle className="h-4 w-4" />
          Docker not running. Start Docker Desktop to run your bot.
        </div>
      )
    }
    return null
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/60 backdrop-blur">
        <div className=" mx-2 px-6 py-4 ">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="ghost" onClick={() => router.push("/projects")}>
                ← Back to Projects
              </Button>
              <Separator orientation="vertical" className="h-6" />
              <div className="flex items-center gap-3">
                <img src="/assets/logo.png" alt="Robin" className="h-5 w-5" />
                <span className="font-semibold">Project: {params.projectId}</span>
                <Badge variant="secondary">Active</Badge>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {renderDockerStatus()}
              {!botRunning ? (
                <Button size="sm" onClick={handleStartBot} disabled={isStarting || dockerStatus === "not_running"}>
                  <Play className="h-4 w-4 mr-2" />
                  {isStarting ? "Starting..." : "Start Bot"}
                </Button>
              ) : (
                <Button size="sm" variant="destructive" onClick={handleStopBot} disabled={isStopping}>
                  <Square className="h-4 w-4 mr-2" />
                  {isStopping ? "Stopping..." : "Stop Bot"}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={handleDeployToRailway}
              >
                <Train className="h-4 w-4 mr-2" />
                Deploy
              </Button>
            </div>
          </div>

          <div className="flex items-center gap-2 mt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (applicationId) {
                  window.open(`https://discord.com/api/oauth2/authorize?client_id=${applicationId}&permissions=0&scope=bot%20applications.commands`, '_blank')
                } else {
                  alert('Application ID not found. Please ensure your bot is properly configured.')
                }
              }}
            >
              <ExternalLink className="h-4 w-4 mr-2" />
              Invite Link
            </Button>
            {railwayUrl && deploymentStatus === "success" && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.open(railwayUrl, '_blank')}
              >
                <Rocket className="h-4 w-4 mr-2" />
                Open Railway
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setShowLogs(!showLogs)}>
              <Terminal className="h-4 w-4 mr-2" />
              {showLogs ? "Hide Logs" : "Show Logs"}
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex h-[calc(100vh-120px)]">
        {/* Logs Panel (conditionally shown) */}
        {showLogs && (
          <div className="w-96 border-r border-border bg-card/70 backdrop-blur flex flex-col">
            <div className="p-4 border-b border-border">
              <h3 className="font-semibold mb-1 flex items-center gap-2">
                <Terminal className="h-4 w-4" />
                Bot Logs
              </h3>
              <p className="text-xs text-muted-foreground">
                {botRunning ? "Live logs (auto-refresh)" : "Start the bot to see logs"}
              </p>
            </div>
            <div className="flex-1 p-3 overflow-auto">
              <pre className="text-xs font-mono whitespace-pre-wrap break-words">
                {botLogs || (dockerStatus === "not_running" ? "Docker not running. Start Docker Desktop." : "No logs yet. Start the bot to see output.")}
              </pre>
            </div>
          </div>
        )}

        {/* Chat Sidebar */}
        <div className="w-96 border-r border-border bg-card/70 backdrop-blur flex flex-col">
          <div className="p-4 border-b border-border">
            <h3 className="font-semibold mb-1 flex items-center gap-2">
              <Bot className="h-4 w-4" />
              AI Assistant
            </h3>
            <p className="text-xs text-muted-foreground">Chat about the codebase and generate snippets.</p>
          </div>
          <div className="flex-1 overflow-auto p-3 space-y-3">
            {messages.map((m) => (
              <div
                key={m.id}
                className={
                  m.role === "user"
                    ? "ml-6 rounded-md border border-primary/20 bg-primary/10 p-2 text-sm"
                    : "mr-6 rounded-md border border-border bg-muted p-2 text-sm"
                }
              >
                <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                  {m.role === "user" ? "You" : "Assistant"}
                </div>
                <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
          <form onSubmit={onSubmitChat} className="p-3 border-t border-border bg-card">
            <div className="flex items-end gap-2">
              <Textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder={isAiThinking ? "AI is thinking..." : "Ask the AI to help..."}
                className="min-h-10 max-h-32 resize-none"
                disabled={isAiThinking}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    if (!isAiThinking) sendMessage(chatInput)
                  }
                }}
              />
              <Button type="submit" size="icon" disabled={!chatInput.trim() || isAiThinking}>
                <Send className="h-4 w-4" />
              </Button>
            </div>
            {isAiThinking && (
              <div className="text-xs text-muted-foreground mt-2 flex items-center gap-2">
                <div className="flex gap-1">
                  <span className="animate-bounce" style={{animationDelay: '0ms'}}>●</span>
                  <span className="animate-bounce" style={{animationDelay: '150ms'}}>●</span>
                  <span className="animate-bounce" style={{animationDelay: '300ms'}}>●</span>
                </div>
                AI is processing your request...
              </div>
            )}
          </form>
        </div>

        {/* File Explorer */}
        <div className="w-80 border-r border-border bg-card/70 backdrop-blur">
          <div className="p-4">
            <h3 className="font-semibold mb-4 flex items-center gap-2">
              <Folder className="h-4 w-4" />
              File Explorer
            </h3>
            <div className="space-y-1">{renderBackendTree(tree)}</div>
          </div>
        </div>

        {/* Code Editor */}
        <div className="flex-1 flex flex-col">
          {selectedFilePath ? (
            <>
              <div className="border-b border-border bg-card/60 backdrop-blur px-4 py-2">
                <div className="flex items-center gap-2">
                  <File className="h-4 w-4" />
                  <span className="font-medium">{selectedFilePath.split('/').pop()}</span>
                </div>
              </div>
              <div className="flex-1 p-4">
                <Card className="h-full">
                  <CardContent className="p-4 h-full">
                    <div className="h-full">
                      <Editor
                        height="calc(100vh - 260px)"
                        theme="vs-dark"
                        path={selectedFilePath || undefined}
                        language={getLanguageForPath(selectedFilePath)}
                        value={(selectedFilePath && contentsByPath[selectedFilePath]) || ""}
                        onChange={(value) => {
                          const v = value ?? ""
                          if (!selectedFilePath) return
                          setContentsByPath((prev) => ({ ...prev, [selectedFilePath]: v }))
                        }}
                        options={{
                          minimap: { enabled: false },
                          fontSize: 14,
                          fontLigatures: true,
                          tabSize: 2,
                          wordWrap: "on",
                          scrollBeyondLastLine: false,
                          smoothScrolling: true,
                        }}
                      />
                      <div className="mt-2 flex justify-end">
                        <Button
                          size="sm"
                          onClick={async () => {
                            if (!selectedFilePath) return
                            try {
                              await writeFileToBackend(selectedFilePath, contentsByPath[selectedFilePath] || "")
                            } catch (e) {
                              console.error(e)
                              alert("Save failed")
                            }
                          }}
                          disabled={!selectedFilePath}
                        >
                          Save
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-muted-foreground">
                <File className="h-12 w-12 mx-auto mb-4 opacity-50" />
                <p>Select a file to view its contents</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function getLanguageForPath(path: string | null): string | undefined {
  if (!path) return undefined
  const lower = path.toLowerCase()
  if (lower.endsWith(".ts")) return "typescript"
  if (lower.endsWith(".tsx")) return "typescript"
  if (lower.endsWith(".js")) return "javascript"
  if (lower.endsWith(".jsx")) return "javascript"
  if (lower.endsWith(".json")) return "json"
  if (lower.endsWith(".md") || lower.endsWith(".mdx")) return "markdown"
  if (lower.endsWith(".css")) return "css"
  if (lower.endsWith(".html")) return "html"
  return undefined
}