"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Bot, Sparkles, Code, Zap } from "lucide-react"
import { useRouter } from "next/navigation"
import { getUserId } from "@/lib/user"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8001"

interface Command {
  name: string
  description: string
}

interface Plan {
  prefix: string
  commands: Command[]
}

export default function CreateBotPage() {
  const [botDescription, setBotDescription] = useState("")
  const [discordToken, setDiscordToken] = useState("")
  const [applicationId, setApplicationId] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [validationError, setValidationError] = useState("")
  const [botName, setBotName] = useState("")
  const [botAvatar, setBotAvatar] = useState("")
  const [showPlan, setShowPlan] = useState(false)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [isLoadingPlan, setIsLoadingPlan] = useState(false)
  const [editedPrefix, setEditedPrefix] = useState("!")
  const [editedCommands, setEditedCommands] = useState<Command[]>([])
  const router = useRouter()

  const handleValidate = async () => {
    if (!discordToken.trim() || !applicationId.trim()) {
      setValidationError("Please provide both Discord token and Application ID")
      return
    }

    setIsValidating(true)
    setValidationError("")

    try {
      const res = await fetch(`${BACKEND_URL}/validate-discord`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: discordToken, application_id: applicationId })
      })
      const data = await res.json()

      if (!data.valid) {
        setValidationError(data.error || "Validation failed")
        return
      }

      setBotName(data.bot_name)
      setBotAvatar(data.bot_avatar || "")
      setShowPlan(true)

      // Generate initial plan
      await generatePlan()
    } catch (err: any) {
      console.error(err)
      setValidationError(err.message || "Failed to validate credentials")
    } finally {
      setIsValidating(false)
    }
  }

  const generatePlan = async () => {
    setIsLoadingPlan(true)
    const startTime = performance.now()
    try {
      const res = await fetch(`${BACKEND_URL}/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: botDescription })
      })
      if (res.ok) {
        const data = await res.json()
        setPlan({ prefix: data.prefix, commands: data.commands })
        setEditedPrefix(data.prefix)
        setEditedCommands(data.commands || [])
        const endTime = performance.now()
        console.log(`Plan generated in ${(endTime - startTime).toFixed(0)}ms`)
      }
    } catch (err) {
      console.error("Failed to generate plan:", err)
    } finally {
      setIsLoadingPlan(false)
    }
  }

  const handleGenerate = async () => {
    setIsGenerating(true)
    const startTime = performance.now()

    try {
      const userId = getUserId()
      console.log("Starting bot generation...")
      const res = await fetch(`${BACKEND_URL}/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: botDescription,
          discordToken: discordToken,
          applicationId: applicationId,
          commands: editedCommands,
          prefix: editedPrefix,
          user_id: userId
        })
      })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error(msg || "Failed to generate project")
      }
      const data = await res.json()
      const projectId = data.projectId
      const endTime = performance.now()
      console.log(`Bot generated in ${((endTime - startTime) / 1000).toFixed(1)}s`)

      // Save application ID to localStorage for the invite link
      localStorage.setItem(`bot_${projectId}_appId`, applicationId)

      // Navigate to editor with auto-start flag
      router.push(`/editor/${projectId}?applicationId=${applicationId}&autoStart=true`)
    } catch (err: any) {
      console.error(err)
      alert(err.message || "Generation failed")
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card/60 backdrop-blur">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <img src="/assets/logo.png" alt="Robin" className="h-8 w-8" />
              <span className="text-xl font-semibold">Robin</span>
            </div>
            <Button variant="outline" onClick={() => router.push("/projects")}>
              My Projects
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-6 py-20">
        <div className="mx-auto max-w-4xl">
          {/* Hero Section */}
          <div className="text-center mb-16">
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground mb-6">
              <Sparkles className="h-4 w-4 text-primary" />
              AI assisted · Instant deploy
            </div>
            <h1 className="text-5xl font-extrabold tracking-tight text-balance">
              Build Discord bots in minutes, not weeks
            </h1>
            <p className="mt-4 text-lg text-muted-foreground text-balance max-w-2xl mx-auto">
              Generate powerful Discord bots instantly with natural language. Just describe what you want, and watch
              your bot come to life.
            </p>
          </div>

          {/* Creation Form */}
          <div className="relative mx-auto max-w-3xl">
            {/* Glow effect */}
            <div className="absolute -inset-1 rounded-2xl opacity-30 blur-xl animate-pulse" style={{ background: 'linear-gradient(to right, #00bca2, #00bca280, #00bca2)' }} />

            <Card className="relative border-2 border-border/80 shadow-2xl backdrop-blur-sm bg-card/95">
              <CardHeader className="space-y-1 pb-6">
                <CardTitle className="flex items-center gap-2 text-2xl">
                  <Code className="h-6 w-6" />
                  Create Your Bot
                </CardTitle>
                <CardDescription className="text-base">
                  {!showPlan
                    ? "Follow the steps below to create and deploy your custom Discord bot"
                    : "Review your bot configuration and generate the project"
                  }
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
              {!showPlan ? (
                <>
                  {/* Step 1 */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: '#00bca2' }}>
                      <div className="flex h-6 w-6 items-center justify-center rounded-full text-xs text-white" style={{ backgroundColor: '#00bca2' }}>
                        1
                      </div>
                      <span>Describe Your Bot</span>
                    </div>
                    <div className="ml-8 space-y-2">
                      <Label htmlFor="description" className="text-base font-medium">What should your bot do?</Label>
                      <Textarea
                        id="description"
                        placeholder="Example: Create a moderation bot with kick, ban, and mute commands. Include a welcome message system and server statistics."
                        value={botDescription}
                        onChange={(e) => setBotDescription(e.target.value)}
                        rows={5}
                        className="resize-none text-base border-2 transition-all focus:ring-2"
                        style={{
                          borderColor: botDescription ? '#00bca2' : undefined,
                          '--tw-ring-color': 'rgba(0, 188, 162, 0.2)'
                        } as React.CSSProperties}
                        onFocus={(e) => e.target.style.borderColor = '#00bca2'}
                        onBlur={(e) => e.target.style.borderColor = botDescription ? '#00bca2' : ''}
                      />
                      <p className="text-xs text-muted-foreground">
                        Be specific about features, commands, and behavior you want
                      </p>
                    </div>
                  </div>

                  <div className="border-t pt-6" />

                  {/* Step 2 */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: '#00bca2' }}>
                      <div className="flex h-6 w-6 items-center justify-center rounded-full text-xs text-white" style={{ backgroundColor: '#00bca2' }}>
                        2
                      </div>
                      <span>Discord Bot Credentials</span>
                    </div>
                    <div className="ml-8 space-y-4">
                      <div className="space-y-2">
                        <Label htmlFor="appId" className="text-base font-medium flex items-center gap-2">
                          Application ID
                          <span className="text-xs font-normal text-muted-foreground">(Required)</span>
                        </Label>
                        <Input
                          id="appId"
                          type="text"
                          placeholder="1234567890123456789"
                          value={applicationId}
                          onChange={(e) => setApplicationId(e.target.value)}
                          className="text-base font-mono h-12 border-2 transition-all focus:ring-2"
                          style={{
                            borderColor: applicationId ? '#00bca2' : undefined,
                            '--tw-ring-color': 'rgba(0, 188, 162, 0.2)'
                          } as React.CSSProperties}
                          onFocus={(e) => (e.target as HTMLInputElement).style.borderColor = '#00bca2'}
                          onBlur={(e) => (e.target as HTMLInputElement).style.borderColor = applicationId ? '#00bca2' : ''}
                        />
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="token" className="text-base font-medium flex items-center gap-2">
                          Bot Token
                          <span className="text-xs font-normal text-muted-foreground">(Required)</span>
                        </Label>
                        <Input
                          id="token"
                          type="password"
                          placeholder="MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.GhJkLm.nOpQrStUvWxYz..."
                          value={discordToken}
                          onChange={(e) => setDiscordToken(e.target.value)}
                          className="text-base font-mono h-12 border-2 transition-all focus:ring-2"
                          style={{
                            borderColor: discordToken ? '#00bca2' : undefined,
                            '--tw-ring-color': 'rgba(0, 188, 162, 0.2)'
                          } as React.CSSProperties}
                          onFocus={(e) => (e.target as HTMLInputElement).style.borderColor = '#00bca2'}
                          onBlur={(e) => (e.target as HTMLInputElement).style.borderColor = discordToken ? '#00bca2' : ''}
                        />
                      </div>

                      <div className="flex items-start gap-3 p-4 rounded-lg border-2" style={{ backgroundColor: 'rgba(0, 188, 162, 0.05)', borderColor: 'rgba(0, 188, 162, 0.2)' }}>
                        <Bot className="h-5 w-5 mt-0.5 flex-shrink-0" style={{ color: '#00bca2' }} />
                        <div className="space-y-2">
                          <p className="text-sm font-semibold text-foreground">Need help finding these?</p>
                          <div className="space-y-1.5">
                            <p className="text-sm text-muted-foreground">
                              <span className="font-semibold text-foreground">1.</span> Go to{" "}
                              <a
                                href="https://discord.com/developers/applications"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="hover:underline font-semibold"
                                style={{ color: '#00bca2' }}
                              >
                                Discord Developer Portal
                              </a>
                            </p>
                            <p className="text-sm text-muted-foreground">
                              <span className="font-semibold text-foreground">2.</span> Select your application → Copy <strong className="text-foreground">Application ID</strong>
                            </p>
                            <p className="text-sm text-muted-foreground">
                              <span className="font-semibold text-foreground">3.</span> Go to <strong className="text-foreground">Bot</strong> tab → Reset Token → Copy token
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {validationError && (
                    <div className="flex items-start gap-2 p-4 rounded-md bg-destructive/10 border border-destructive/20 text-destructive">
                      <span className="text-lg">⚠️</span>
                      <div>
                        <p className="font-medium text-sm">Validation Failed</p>
                        <p className="text-sm">{validationError}</p>
                      </div>
                    </div>
                  )}

                  {botName && (
                    <div className="flex items-start gap-2 p-4 rounded-md bg-primary/10 border border-primary/20 text-primary">
                      <span className="text-lg">✓</span>
                      <div>
                        <p className="font-medium text-sm">Bot Validated Successfully</p>
                        <p className="text-sm">Connected to: <strong>{botName}</strong></p>
                      </div>
                    </div>
                  )}

                  <div className="border-t pt-6" />

                  <Button
                    onClick={handleValidate}
                    disabled={isValidating || !discordToken.trim() || !applicationId.trim() || !botDescription.trim()}
                    className="w-full h-14 text-base font-semibold shadow-lg hover:shadow-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ backgroundColor: '#00bca2', color: 'black' }}
                    size="lg"
                  >
                    {isValidating ? (
                      <>
                        <div className="mr-2 h-5 w-5 animate-spin rounded-full border-2 border-black border-t-transparent" />
                        Validating Credentials...
                      </>
                    ) : (
                      <>
                        <Zap className="mr-2 h-5 w-5" style={{ color: 'black' }} />
                        Validate & Continue to Generation
                      </>
                    )}
                  </Button>
                </>
              ) : (
                <>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-semibold">Generation Plan</h3>
                      <Badge variant="secondary">Ready to Generate</Badge>
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-start gap-4">
                        {botAvatar && (
                          <img
                            src={botAvatar}
                            alt={botName}
                            className="w-16 h-16 rounded-full border-2"
                            style={{ borderColor: 'rgba(0, 188, 162, 0.3)' }}
                          />
                        )}
                        <div className="flex-1">
                          <p className="text-base font-semibold mb-2">Bot: {botName}</p>
                          <p className="text-sm text-muted-foreground">
                            {botDescription}
                          </p>
                        </div>
                      </div>

                      {isLoadingPlan && (
                        <div className="p-4 rounded-lg border-2 text-center" style={{ backgroundColor: 'rgba(0, 188, 162, 0.05)', borderColor: 'rgba(0, 188, 162, 0.2)' }}>
                          <p className="text-sm text-muted-foreground">⏳ Generating command plan...</p>
                        </div>
                      )}

                      {plan && !isLoadingPlan && (
                        <div className="space-y-3 p-4 rounded-lg border-2" style={{ backgroundColor: 'rgba(0, 188, 162, 0.05)', borderColor: 'rgba(0, 188, 162, 0.2)' }}>
                          <p className="text-sm font-semibold">Plan:</p>


                          <div className="space-y-3">
                            <div>
                              <Label className="text-xs">Command Prefix</Label>
                              <Input
                                value={editedPrefix}
                                onChange={(e) => setEditedPrefix(e.target.value)}
                                className="h-8 mt-1"
                                placeholder="!"
                                maxLength={3}
                                style={{ borderColor: 'rgba(0, 188, 162, 0.3)' }}
                              />
                            </div>

                            <div>
                              <Label className="text-xs mb-2 block">Commands:</Label>
                              <div className="space-y-3">
                                {editedCommands.map((cmd, i) => (
                                  <div key={i} className="space-y-2 p-3 rounded-lg border" style={{ backgroundColor: 'rgba(0, 0, 0, 0.02)', borderColor: 'rgba(0, 188, 162, 0.2)' }}>
                                    <div className="flex gap-2 items-center">
                                      <div className="flex-1">
                                        <Label className="text-xs text-muted-foreground mb-1 block">Command Name</Label>
                                        <div className="flex gap-1 items-center">
                                          <span className="text-sm font-mono" style={{ color: '#00bca2' }}>{editedPrefix}</span>
                                          <Input
                                            value={cmd.name}
                                            onChange={(e) => {
                                              const updated = [...editedCommands]
                                              updated[i] = { ...updated[i], name: e.target.value }
                                              setEditedCommands(updated)
                                            }}
                                            className="h-8 font-mono"
                                            placeholder="command_name"
                                            style={{ borderColor: 'rgba(0, 188, 162, 0.3)' }}
                                          />
                                        </div>
                                      </div>
                                      <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => setEditedCommands(editedCommands.filter((_, idx) => idx !== i))}
                                        className="h-8 px-2 mt-5"
                                      >
                                        ✕
                                      </Button>
                                    </div>
                                    <div>
                                      <Label className="text-xs text-muted-foreground mb-1 block">Description</Label>
                                      <Textarea
                                        value={cmd.description}
                                        onChange={(e) => {
                                          const updated = [...editedCommands]
                                          updated[i] = { ...updated[i], description: e.target.value }
                                          setEditedCommands(updated)
                                        }}
                                        className="text-xs resize-none"
                                        placeholder="What this command does..."
                                        rows={2}
                                        style={{
                                          backgroundColor: 'rgba(128, 128, 128, 0.05)',
                                          borderColor: 'rgba(128, 128, 128, 0.2)',
                                          color: '#6b7280'
                                        }}
                                      />
                                    </div>
                                  </div>
                                ))}
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setEditedCommands([...editedCommands, { name: "", description: "" }])}
                                  className="h-8 w-full text-xs"
                                  style={{ borderColor: 'rgba(0, 188, 162, 0.3)', color: '#00bca2' }}
                                >
                                  + Add Command
                                </Button>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {isGenerating && (
                        <div className="p-3 rounded-lg bg-muted/50 border">
                          <p className="text-xs text-muted-foreground">⏳ Generating your bot code...</p>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={() => {
                        setShowPlan(false)
                        setBotName("")
                        setBotAvatar("")
                        setPlan(null)
                      }}
                      disabled={isGenerating || isLoadingPlan}
                      className="flex-1"
                    >
                      Back
                    </Button>
                    <Button
                      onClick={handleGenerate}
                      disabled={isGenerating || isLoadingPlan || !plan}
                      className="flex-1 h-12"
                      style={{ backgroundColor: '#00bca2', color: 'black' }}
                      size="lg"
                    >
                      {isGenerating ? (
                        <>
                          <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-black border-t-transparent" />
                          Generating Bot...
                        </>
                      ) : (
                        <>
                          <Zap className="mr-2 h-4 w-4" style={{ color: 'black' }} />
                          Generate Bot
                        </>
                      )}
                    </Button>
                  </div>
                </>
              )}
              </CardContent>
            </Card>
          </div>

          {/* Technologies Showcase */}
          <div className="mt-16 p-8 rounded-2xl border-2" style={{ backgroundColor: '#000000', borderColor: '' }}>
            <h2 className="text-2xl font-bold mb-6 text-center text-white">🏆 Powered by Cutting-Edge AI</h2>
            <div className="grid gap-6 md:grid-cols-2 max-w-2xl mx-auto">
              <div className="p-6 rounded-xl border-2 transition-all hover:shadow-lg hover:shadow-[#00bca2]/20" style={{ backgroundColor: '#000000', borderColor: '#00bca2' }}>
                <div className="flex items-start gap-4">
                  <div className="text-4xl flex-shrink-0">⚡</div>
                  <div>
                    <h3 className="font-bold text-lg mb-2" style={{ color: '#00bca2' }}>Cerebras API</h3>
                    <p className="text-sm leading-relaxed text-gray-300">World's fastest AI chip - 2600 tokens/s code generation</p>
                  </div>
                </div>
              </div>
              <div className="p-6 rounded-xl border-2 transition-all hover:shadow-lg hover:shadow-[#00bca2]/20" style={{ backgroundColor: '#000000', borderColor: '#00bca2' }}>
                <div className="flex items-start gap-4">
                  <div className="text-4xl flex-shrink-0">🦙</div>
                  <div>
                    <h3 className="font-bold text-lg mb-2" style={{ color: '#00bca2' }}>Meta Llama</h3>
                    <p className="text-sm leading-relaxed text-gray-300">Creative bot personalities and engaging descriptions</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Features */}
          <div className="mt-8 grid gap-6 md:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Instant Generation</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Generate fully functional Discord bots in seconds with AI-powered code generation
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Custom Commands</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Create bots with custom commands, data persistence, and interactive features
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Live Testing</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground">
                  Test your bot locally with real-time logs and instant code updates
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  )
}
