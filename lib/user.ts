/**
 * User identification utility for anonymous users
 * Generates and persists a unique user ID in localStorage
 */

const USER_ID_KEY = "botforge_user_id"

/**
 * Generate a random user ID
 */
function generateUserId(): string {
  return `user_${Date.now()}_${Math.random().toString(36).substring(2, 15)}`
}

/**
 * Get or create user ID from localStorage
 * This persists across sessions in the same browser
 */
export function getUserId(): string {
  // Check if we're in browser environment
  if (typeof window === "undefined") {
    return ""
  }

  // Try to get existing user ID
  let userId = localStorage.getItem(USER_ID_KEY)

  // If no user ID exists, create one
  if (!userId) {
    userId = generateUserId()
    localStorage.setItem(USER_ID_KEY, userId)
    console.log("[UserID] Created new user ID:", userId)
  }

  return userId
}

/**
 * Clear user ID (for testing purposes)
 */
export function clearUserId(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(USER_ID_KEY)
  }
}
