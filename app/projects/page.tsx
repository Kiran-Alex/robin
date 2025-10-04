"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Bot, Plus, Search, Calendar, Code, ExternalLink, Trash2 } from "lucide-react"
import { useRouter } from "next/navigation"
import { getUserId } from "@/lib/user"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8001"

interface Project {
  id: string
  name: string
  description: string
  status: "active" | "inactive" | "deploying"
  created_at: string
  modified_at: string
  application_id?: string
}

export default function ProjectsPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()

  // Fetch projects on mount
  useEffect(() => {
    fetchProjects()
  }, [])

  const fetchProjects = async () => {
    const startTime = performance.now()
    try {
      const userId = getUserId()
      const res = await fetch(`${BACKEND_URL}/projects?user_id=${userId}`, {
        cache: 'no-store',  // Disable Next.js caching for real-time data
      })
      if (res.ok) {
        const data = await res.json()
        setProjects(data.projects || [])
        const endTime = performance.now()
        console.log(`Projects loaded in ${(endTime - startTime).toFixed(0)}ms`)
      }
    } catch (err) {
      console.error("Failed to fetch projects:", err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDelete = async (projectId: string) => {
    if (!confirm("Are you sure you want to delete this project? This action cannot be undone.")) {
      return
    }

    try {
      const userId = getUserId()
      const res = await fetch(`${BACKEND_URL}/projects/${projectId}?user_id=${userId}`, {
        method: "DELETE"
      })

      if (res.ok) {
        // Refresh projects list
        fetchProjects()
      } else {
        alert("Failed to delete project")
      }
    } catch (err) {
      console.error("Failed to delete project:", err)
      alert("Failed to delete project")
    }
  }

  const handleInvite = (applicationId: string | undefined) => {
    if (!applicationId) {
      alert("No application ID found for this project")
      return
    }

    // Discord OAuth2 invite URL with bot scope and admin permissions
    const inviteUrl = `https://discord.com/api/oauth2/authorize?client_id=${applicationId}&permissions=8&scope=bot`
    window.open(inviteUrl, "_blank")
  }

  const filteredProjects = projects.filter(
    (project) =>
      project.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      project.description.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  const getStatusColor = (status: string) => {
    switch (status) {
      case "active":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      case "inactive":
        return "bg-gray-500/10 text-gray-500 border-gray-500/20"
      case "deploying":
        return "bg-blue-500/10 text-blue-500 border-blue-500/20"
      default:
        return "bg-gray-500/10 text-gray-500 border-gray-500/20"
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
            <Button onClick={() => router.push("/")}>
              <Plus className="h-4 w-4 mr-2" />
              Create New Bot
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-6 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">My Projects</h1>
          <p className="text-muted-foreground">Manage and deploy your Discord bots</p>
        </div>

        {/* Search */}
        <div className="mb-6">
          <div className="relative max-w-md">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search projects..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>
        </div>

        {/* Projects Grid */}
        {isLoading ? (
          <div className="text-center py-12">
            <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground opacity-50 animate-pulse" />
            <h3 className="text-lg font-semibold mb-2">Loading projects...</h3>
          </div>
        ) : filteredProjects.length > 0 ? (
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {filteredProjects.map((project) => (
              <Card
                key={project.id}
                className="cursor-pointer hover:shadow-lg transition-all hover:-translate-y-0.5 border-border/60"
                onClick={() => router.push(`/editor/${project.id}`)}
              >
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Bot className="h-5 w-5 text-primary" />
                      <CardTitle className="text-lg">{project.name}</CardTitle>
                    </div>
                    <Badge className={getStatusColor(project.status)}>{project.status}</Badge>
                  </div>
                  <CardDescription className="text-sm">{project.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 text-sm text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <Calendar className="h-4 w-4" />
                      <span>Created: {new Date(project.created_at).toLocaleDateString()}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Code className="h-4 w-4" />
                      <span>Modified: {new Date(project.modified_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <div className="flex gap-2 mt-4">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        router.push(`/editor/${project.id}`)
                      }}
                    >
                      <Code className="h-4 w-4 mr-1" />
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleInvite(project.application_id)
                      }}
                      disabled={!project.application_id}
                    >
                      <ExternalLink className="h-4 w-4 mr-1" />
                      Invite
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(project.id)
                      }}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      Delete
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground opacity-50" />
            <h3 className="text-lg font-semibold mb-2">No projects found</h3>
            <p className="text-muted-foreground mb-4">
              {searchQuery ? "Try adjusting your search terms" : "Create your first Discord bot to get started"}
            </p>
            <Button onClick={() => router.push("/")}>
              <Plus className="h-4 w-4 mr-2" />
              Create New Bot
            </Button>
          </div>
        )}
      </main>
    </div>
  )
}
