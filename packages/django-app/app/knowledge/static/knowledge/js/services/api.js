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

  async createPage(
    title,
    content,
    slug,
    isPublished = true,
    pageType = "page"
  ) {
    return await this.request("/knowledge/api/pages/", {
      method: "POST",
      body: JSON.stringify({
        title,
        content,
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
