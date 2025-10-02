"use client"

import { useCallback, useEffect, useRef } from "react"
import type { ReactNode } from "react"
import confetti from "canvas-confetti"

interface ConfettiButtonProps {
  children?: ReactNode
  className?: string
  onClick?: () => void
}

export function ConfettiButton({
  children,
  className = "",
  onClick,
}: ConfettiButtonProps) {
  const buttonRef = useRef<HTMLButtonElement>(null)

  const handleClick = useCallback(() => {
    const button = buttonRef.current
    if (!button) return

    const rect = button.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2

    confetti({
      particleCount: 100,
      spread: 70,
      origin: {
        x: x / window.innerWidth,
        y: y / window.innerHeight,
      },
    })

    onClick?.()
  }, [onClick])

  return (
    <button ref={buttonRef} onClick={handleClick} className={className}>
      {children}
    </button>
  )
}

interface ConfettiProps {
  particleCount?: number
  spread?: number
}

export function triggerConfetti({ particleCount = 100, spread = 70 }: ConfettiProps = {}) {
  confetti({
    particleCount,
    spread,
    origin: { y: 0.6 },
  })
}
