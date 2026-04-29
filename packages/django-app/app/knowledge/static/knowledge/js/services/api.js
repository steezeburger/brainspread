// API Service for Knowledge Base App
class ApiService {
  constructor() {
    this.baseURL = window.location.origin;
    this.token = localStorage.getItem("authToken");
  }

  // Get CSRF token from cookies
  getCsrfToken() {
    const name = "csrftoken";
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  async request(url, options = {}) {
    const config = {
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      ...options,
    };

    // Add CSRF token for non-GET requests
    if (options.method && options.method !== "GET") {
      const csrfToken = this.getCsrfToken();
      if (csrfToken) {
        config.headers["X-CSRFToken"] = csrfToken;
      }
    }

    if (this.token) {
      config.headers["Authorization"] = `Token ${this.token}`;
    }

    try {
      const response = await fetch(`${this.baseURL}${url}`, config);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || data.errors?.non_field_errors?.[0] || "Request failed"
        );
      }

      return data;
    } catch (error) {
      console.error("API Error:", error);
      throw error;
    }
  }

  // Auth methods
  async login(email, password) {
    // Detect user's timezone
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

    const data = await this.request("/api/auth/login/", {
      method: "POST",
      body: JSON.stringify({ email, password, timezone }),
    });

    if (data.success) {
      this.token = data.data.token;
      localStorage.setItem("authToken", this.token);
      localStorage.setItem("user", JSON.stringify(data.data.user));
    }

    return data;
  }

  async register(email, password) {
    const data = await this.request("/api/auth/register/", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    if (data.success) {
      this.token = data.data.token;
      localStorage.setItem("authToken", this.token);
      localStorage.setItem("user", JSON.stringify(data.data.user));
    }

    return data;
  }

  async logout() {
    try {
      await this.request("/api/auth/logout/", { method: "POST" });
    } finally {
      this.token = null;
      localStorage.removeItem("authToken");
      localStorage.removeItem("user");
    }
  }

  async me() {
    return await this.request("/api/auth/me/");
  }

  async createPage(title, slug, isPublished = true, pageType = "page") {
    return await this.request("/knowledge/api/pages/", {
      method: "POST",
      body: JSON.stringify({
        title,
        slug,
        is_published: isPublished,
        page_type: pageType,
      }),
    });
  }

  async updatePage(pageUuid, updates) {
    return await this.request("/knowledge/api/pages/update/", {
      method: "PUT",
      body: JSON.stringify({
        page: pageUuid,
        ...updates,
      }),
    });
  }

  async deletePage(pageUuid) {
    return await this.request("/knowledge/api/pages/delete/", {
      method: "DELETE",
      body: JSON.stringify({ page: pageUuid }),
    });
  }

  async getPages(publishedOnly = true, limit = 10, offset = 0) {
    return await this.request(
      `/knowledge/api/pages/list/?published_only=${publishedOnly}&limit=${limit}&offset=${offset}`
    );
  }

  async searchPages(query, limit = 10) {
    return await this.request(
      `/knowledge/api/pages/search/?query=${encodeURIComponent(query)}&limit=${limit}`
    );
  }

  // New block-centric methods
  async getPageWithBlocks(pageUuid = null, date = null, slug = null) {
    let params = "";
    if (pageUuid) {
      params = `?page=${pageUuid}`;
    } else if (date) {
      params = `?date=${date}`;
    } else if (slug) {
      params = `?slug=${slug}`;
    }

    return await this.request(`/knowledge/api/page/${params}`);
  }

  async createBlock(blockData) {
    return await this.request("/knowledge/api/blocks/", {
      method: "POST",
      body: JSON.stringify(blockData),
    });
  }

  async updateBlock(blockUuid, updateData) {
    const requestData = {
      block: blockUuid,
      ...updateData,
    };

    return await this.request("/knowledge/api/blocks/update/", {
      method: "PUT",
      body: JSON.stringify(requestData),
    });
  }

  async reorderBlocks(blocksOrderData) {
    return await this.request("/knowledge/api/blocks/reorder/", {
      method: "PUT",
      body: JSON.stringify({ blocks: blocksOrderData }),
    });
  }

  async deleteBlock(blockUuid) {
    return await this.request("/knowledge/api/blocks/delete/", {
      method: "DELETE",
      body: JSON.stringify({ block: blockUuid }),
    });
  }

  async toggleBlockTodo(blockUuid) {
    return await this.request("/knowledge/api/blocks/toggle-todo/", {
      method: "POST",
      body: JSON.stringify({ block: blockUuid }),
    });
  }

  /**
   * Set or clear a block's scheduled_for date.
   *   scheduledFor: "" or "YYYY-MM-DD"   (empty clears the schedule)
   *   reminderDate: "" or "YYYY-MM-DD"   (the day the reminder fires;
   *                                       defaults to scheduledFor on the
   *                                       backend if omitted, so callers
   *                                       can leave this empty for
   *                                       "remind day-of")
   *   reminderTime: "" or "HH:MM"        (presence triggers reminder
   *                                       creation; user-local time)
   * Re-saving always replaces any pending reminder for the block.
   */
  async scheduleBlock(
    blockUuid,
    scheduledFor,
    reminderDate = "",
    reminderTime = ""
  ) {
    const payload = {
      block: blockUuid,
      scheduled_for: scheduledFor || "",
      reminder_date: reminderDate || "",
      reminder_time: reminderTime || "",
    };
    return await this.request("/knowledge/api/blocks/schedule/", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async moveUndoneTodos(targetDate = null) {
    const body = targetDate ? { target_date: targetDate } : {};
    return await this.request("/knowledge/api/blocks/move-undone-todos/", {
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  async moveBlockToDaily(blockUuid, targetDate = null) {
    const body = { block: blockUuid };
    if (targetDate) {
      body.target_date = targetDate;
    }
    return await this.request("/knowledge/api/blocks/move-to-daily/", {
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  async bulkDeleteBlocks(blockUuids) {
    return await this.request("/knowledge/api/blocks/bulk-delete/", {
      method: "POST",
      body: JSON.stringify({ blocks: blockUuids }),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  async bulkMoveBlocks(blockUuids, targetDate = null) {
    const body = { blocks: blockUuids };
    if (targetDate) {
      body.target_date = targetDate;
    }
    return await this.request("/knowledge/api/blocks/bulk-move/", {
      method: "POST",
      body: JSON.stringify(body),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }

  async getHistoricalData(daysBack = 30, limit = 50) {
    return await this.request(
      `/knowledge/api/historical/?days_back=${daysBack}&limit=${limit}`
    );
  }

  async getTagContent(tagName) {
    return await this.request(
      `/knowledge/api/tag/${encodeURIComponent(tagName)}/`
    );
  }

  async captureWebArchive(blockUuid, url) {
    return await this.request("/api/web-archives/capture/", {
      method: "POST",
      body: JSON.stringify({ block: blockUuid, url }),
    });
  }

  async getWebArchive(blockUuid) {
    return await this.request(`/api/web-archives/by-block/${blockUuid}/`);
  }

  async fetchWebArchiveReadableBlob(blockUuid) {
    // Token auth lives in localStorage, so we can't just <a target="_blank"> -
    // that GET wouldn't carry the Authorization header. Fetch here, hand the
    // caller a Blob, and they turn it into an object URL to open in a tab.
    const headers = {};
    if (this.token) {
      headers["Authorization"] = `Token ${this.token}`;
    }
    const response = await fetch(
      `${this.baseURL}/api/web-archives/by-block/${blockUuid}/readable/`,
      { headers }
    );
    if (!response.ok) {
      throw new Error(`archive fetch failed: ${response.status}`);
    }
    return await response.blob();
  }

  async getGraphData({ includeDaily = false, includeOrphans = true } = {}) {
    const params = new URLSearchParams({
      include_daily: includeDaily ? "true" : "false",
      include_orphans: includeOrphans ? "true" : "false",
    });
    return await this.request(`/knowledge/api/graph/?${params.toString()}`);
  }

  // Utility methods
  isAuthenticated() {
    return !!this.token;
  }

  getCurrentUser() {
    const user = localStorage.getItem("user");
    return user ? JSON.parse(user) : null;
  }

  // Timezone detection and management
  getCurrentBrowserTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch (error) {
      console.warn("Could not detect timezone:", error);
      return "UTC";
    }
  }

  checkTimezoneChange() {
    const currentUser = this.getCurrentUser();
    if (!currentUser || !currentUser.timezone) {
      return false;
    }

    const browserTimezone = this.getCurrentBrowserTimezone();
    const storedTimezone = currentUser.timezone;

    return browserTimezone !== storedTimezone;
  }

  async updateUserTimezone(newTimezone) {
    try {
      const result = await this.request("/api/auth/update-timezone/", {
        method: "POST",
        body: JSON.stringify({ timezone: newTimezone }),
      });

      if (result.success) {
        // Update local storage
        const currentUser = this.getCurrentUser();
        if (currentUser) {
          currentUser.timezone = newTimezone;
          localStorage.setItem("user", JSON.stringify(currentUser));
        }
      }

      return result;
    } catch (error) {
      console.error("Failed to update timezone:", error);
      throw error;
    }
  }

  async updateDiscordWebhookUrl(url) {
    const result = await this.request("/api/auth/update-discord-webhook/", {
      method: "POST",
      body: JSON.stringify({ discord_webhook_url: url || "" }),
    });
    if (result.success) {
      const currentUser = this.getCurrentUser();
      if (currentUser) {
        currentUser.discord_webhook_url = url || "";
        localStorage.setItem("user", JSON.stringify(currentUser));
      }
    }
    return result;
  }

  async updateDiscordUserId(discordUserId) {
    const result = await this.request("/api/auth/update-discord-user-id/", {
      method: "POST",
      body: JSON.stringify({ discord_user_id: discordUserId || "" }),
    });
    if (result.success) {
      const currentUser = this.getCurrentUser();
      if (currentUser) {
        currentUser.discord_user_id = discordUserId || "";
        localStorage.setItem("user", JSON.stringify(currentUser));
      }
    }
    return result;
  }

  async updateUserTimeFormat(newFormat) {
    try {
      const result = await this.request("/api/auth/update-time-format/", {
        method: "POST",
        body: JSON.stringify({ time_format: newFormat }),
      });
      if (result.success) {
        const currentUser = this.getCurrentUser();
        if (currentUser) {
          currentUser.time_format = newFormat;
          localStorage.setItem("user", JSON.stringify(currentUser));
        }
      }
      return result;
    } catch (error) {
      console.error("Failed to update time format:", error);
      throw error;
    }
  }

  async updateUserTheme(newTheme) {
    try {
      const result = await this.request("/api/auth/update-theme/", {
        method: "POST",
        body: JSON.stringify({ theme: newTheme }),
      });

      if (result.success) {
        // Update local storage
        const currentUser = this.getCurrentUser();
        if (currentUser) {
          currentUser.theme = newTheme;
          localStorage.setItem("user", JSON.stringify(currentUser));
        }
      }

      return result;
    } catch (error) {
      console.error("Failed to update theme:", error);
      throw error;
    }
  }

  async sendAIMessage(payload) {
    return await this.request("/api/ai-chat/send/", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async *streamAIMessage(payload) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    const csrfToken = this.getCsrfToken();
    if (csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }
    if (this.token) {
      headers["Authorization"] = `Token ${this.token}`;
    }

    const response = await fetch(`${this.baseURL}/api/ai-chat/stream/`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let detail = "Streaming request failed";
      try {
        const data = await response.json();
        detail = data.error || data.detail || detail;
      } catch (_) {
        // non-JSON error body
      }
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            yield JSON.parse(raw);
          } catch (e) {
            console.error("Failed to parse SSE frame:", raw, e);
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  async *resumeApproval(approvalId, payload) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    const csrfToken = this.getCsrfToken();
    if (csrfToken) {
      headers["X-CSRFToken"] = csrfToken;
    }
    if (this.token) {
      headers["Authorization"] = `Token ${this.token}`;
    }

    const response = await fetch(
      `${this.baseURL}/api/ai-chat/approvals/${approvalId}/resume/`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      }
    );

    if (!response.ok) {
      let detail = "Resume request failed";
      try {
        const data = await response.json();
        detail = data.error || data.detail || detail;
      } catch (_) {
        // non-JSON error body
      }
      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            yield JSON.parse(raw);
          } catch (e) {
            console.error("Failed to parse SSE frame:", raw, e);
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  async getChatSessions() {
    return await this.request("/api/ai-chat/sessions/");
  }

  async getChatSessionDetail(sessionId) {
    return await this.request(`/api/ai-chat/sessions/${sessionId}/`);
  }

  async getAISettings() {
    return await this.request("/api/ai-chat/settings/");
  }

  async updateAISettings(settings) {
    return await this.request("/api/ai-chat/settings/update/", {
      method: "POST",
      body: JSON.stringify(settings),
    });
  }
}

// Export for use in other files
window.apiService = new ApiService();

/**
 * Format an "HH:MM" string per the current user's time_format preference.
 *   "17:30" + "24h" -> "17:30"
 *   "17:30" + "12h" -> "5:30 PM"
 * Falls back to the input on parse failure.
 */
window.formatTimeForUser = function (hhmm, timeFormat) {
  if (!hhmm) return "";
  const parts = String(hhmm).split(":");
  if (parts.length < 2) return hhmm;
  const h = parseInt(parts[0], 10);
  const m = parseInt(parts[1], 10);
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
  const fmt =
    timeFormat || window.apiService.getCurrentUser()?.time_format || "12h";
  if (fmt === "12h") {
    const period = h >= 12 ? "PM" : "AM";
    const h12 = ((h + 11) % 12) + 1;
    return `${h12}:${String(m).padStart(2, "0")} ${period}`;
  }
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};
