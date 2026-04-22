const ChatPanel = {
  name: "ChatPanel",
  components: {
    ChatHistory: window.ChatHistory,
  },
  props: {
    chatContextBlocks: {
      type: Array,
      default: () => [],
    },
    visibleBlocks: {
      type: Array,
      default: () => [],
    },
  },
  emits: ["open-settings", "remove-context-block", "clear-context"],
  data() {
    return {
      isOpen: this.loadOpenState(),
      message: "",
      messages: [],
      loading: false,
      width: this.loadWidth(),
      isResizing: false,
      minWidth: 300,
      maxWidth: 800,
      currentSessionId: null,
      showModelSelector: false,
      aiSettings: null,
      selectedModel: null,
      showContextArea: false,
      messageMenus: {},
      expandedThinking: {},
      expandedToolCalls: {},
      expandedToolCall: {},
      enableNotesTools: this.loadNotesToolsPref(),
      enableNotesWriteTools: this.loadNotesWriteToolsPref(),
      autoApproveNotesWrites: this.loadAutoApprovePref(),
      enableWebSearch: this.loadWebSearchPref(),
      showToolsMenu: false,
      // { [assistantMsgIndex]: { approval_id, tool_uses, decisions: {tool_use_id: "approve"|"reject"}, submitting } }
      pendingApprovals: {},
    };
  },
  mounted() {
    this.setupResizeListener();
    this.loadAISettings();
    this.loadLastChatSession();
    this.setupDocumentListener();
    this.setupClickOutsideListener();
  },
  beforeUnmount() {
    this.removeResizeListener();
    this.removeDocumentListener();
    this.removeClickOutsideListener();
  },
  watch: {
    messages: {
      handler() {
        // Auto-scroll when messages array changes (new messages added)
        this.scrollToBottom();
        // Apply syntax highlighting to new messages
        this.highlightCode();
      },
      deep: true,
    },
  },
  computed: {
    sessionStats() {
      let inputTokens = 0;
      let outputTokens = 0;
      let cacheRead = 0;
      let cacheCreation = 0;
      let turns = 0;
      for (const msg of this.messages) {
        if (msg.role !== "assistant" || !msg.usage) continue;
        turns += 1;
        inputTokens += msg.usage.input_tokens || 0;
        outputTokens += msg.usage.output_tokens || 0;
        cacheRead += msg.usage.cache_read_input_tokens || 0;
        cacheCreation += msg.usage.cache_creation_input_tokens || 0;
      }
      const totalInput = inputTokens + cacheRead + cacheCreation;
      const cacheRatio = totalInput > 0 ? cacheRead / totalInput : 0;
      return {
        turns,
        inputTokens,
        outputTokens,
        cacheRead,
        cacheCreation,
        totalInput,
        cacheRatio,
      };
    },
    hasSessionStats() {
      return this.sessionStats.turns > 0;
    },
    hasActiveTools() {
      return (
        this.enableNotesTools ||
        this.enableNotesWriteTools ||
        this.enableWebSearch
      );
    },
    autoApproveActive() {
      // Only meaningful when write tools are actually granted.
      return this.enableNotesWriteTools && this.autoApproveNotesWrites;
    },
  },
  methods: {
    loadOpenState() {
      const saved = localStorage.getItem("chatPanel.isOpen");
      return saved !== null ? JSON.parse(saved) : true;
    },
    loadWidth() {
      const saved = localStorage.getItem("chatPanel.width");
      return saved ? parseInt(saved) : 400;
    },
    loadLastSessionId() {
      return localStorage.getItem("chatPanel.lastSessionId");
    },
    saveLastSessionId(sessionId) {
      if (sessionId) {
        localStorage.setItem("chatPanel.lastSessionId", sessionId);
      } else {
        localStorage.removeItem("chatPanel.lastSessionId");
      }
    },
    saveOpenState() {
      localStorage.setItem("chatPanel.isOpen", JSON.stringify(this.isOpen));
    },
    loadNotesToolsPref() {
      const saved = localStorage.getItem("chatPanel.enableNotesTools");
      return saved === null ? false : JSON.parse(saved);
    },
    loadNotesWriteToolsPref() {
      const saved = localStorage.getItem("chatPanel.enableNotesWriteTools");
      return saved === null ? false : JSON.parse(saved);
    },
    loadAutoApprovePref() {
      const saved = localStorage.getItem("chatPanel.autoApproveNotesWrites");
      return saved === null ? false : JSON.parse(saved);
    },
    loadWebSearchPref() {
      const saved = localStorage.getItem("chatPanel.enableWebSearch");
      return saved === null ? true : JSON.parse(saved);
    },
    toggleNotesTools() {
      this.enableNotesTools = !this.enableNotesTools;
      localStorage.setItem(
        "chatPanel.enableNotesTools",
        JSON.stringify(this.enableNotesTools)
      );
    },
    toggleNotesWriteTools() {
      this.enableNotesWriteTools = !this.enableNotesWriteTools;
      localStorage.setItem(
        "chatPanel.enableNotesWriteTools",
        JSON.stringify(this.enableNotesWriteTools)
      );
      // Disabling write tools makes auto-approve meaningless; clear it so
      // the toggle's persisted state stays consistent with the gate.
      if (!this.enableNotesWriteTools && this.autoApproveNotesWrites) {
        this.autoApproveNotesWrites = false;
        localStorage.setItem(
          "chatPanel.autoApproveNotesWrites",
          JSON.stringify(false)
        );
      }
    },
    toggleAutoApproveNotesWrites() {
      this.autoApproveNotesWrites = !this.autoApproveNotesWrites;
      localStorage.setItem(
        "chatPanel.autoApproveNotesWrites",
        JSON.stringify(this.autoApproveNotesWrites)
      );
    },
    toggleWebSearch() {
      this.enableWebSearch = !this.enableWebSearch;
      localStorage.setItem(
        "chatPanel.enableWebSearch",
        JSON.stringify(this.enableWebSearch)
      );
    },
    toggleToolsMenu() {
      this.showToolsMenu = !this.showToolsMenu;
    },
    saveWidth() {
      localStorage.setItem("chatPanel.width", this.width.toString());
    },
    togglePanel() {
      this.isOpen = !this.isOpen;
      this.saveOpenState();
    },
    async sendMessage() {
      if (!this.message) return;
      if (!this.selectedModel) {
        console.error("No model selected");
        this.messages.push({
          role: "assistant",
          content:
            "Error: No AI model selected. Please select a model or configure your API keys in settings.",
          created_at: new Date().toISOString(),
        });
        return;
      }
      const userMsg = {
        role: "user",
        content: this.message,
        created_at: new Date().toISOString(),
      };
      this.messages.push(userMsg);
      const payload = {
        message: this.message,
        model: this.selectedModel,
        session_id: this.currentSessionId,
        context_blocks: this.chatContextBlocks,
        enable_notes_tools: this.enableNotesTools,
        enable_notes_write_tools: this.enableNotesWriteTools,
        auto_approve_notes_writes: this.autoApproveActive,
        enable_web_search: this.enableWebSearch,
      };
      this.message = "";
      this.loading = true;

      const assistantMsg = {
        role: "assistant",
        content: "",
        thinking: "",
        tool_events: [],
        created_at: new Date().toISOString(),
        usage: null,
        ai_model: null,
        streaming: true,
      };
      this.messages.push(assistantMsg);
      const assistantIndex = this.messages.length - 1;

      try {
        let streamed = false;
        for await (const event of window.apiService.streamAIMessage(payload)) {
          streamed = true;
          if (event.type === "session") {
            if (event.session_id && !this.currentSessionId) {
              this.currentSessionId = event.session_id;
              this.saveLastSessionId(event.session_id);
            }
          } else if (event.type === "text") {
            this.messages[assistantIndex].content += event.delta || "";
          } else if (event.type === "thinking") {
            this.messages[assistantIndex].thinking =
              (this.messages[assistantIndex].thinking || "") +
              (event.delta || "");
          } else if (event.type === "tool_use") {
            if (!this.messages[assistantIndex].tool_events) {
              this.messages[assistantIndex].tool_events = [];
            }
            this.messages[assistantIndex].tool_events.push({
              type: "tool_use",
              tool_use_id: event.tool_use_id,
              name: event.name,
              input: event.input || {},
            });
            this.autoExpandToolCalls(assistantIndex);
          } else if (event.type === "tool_result") {
            if (!this.messages[assistantIndex].tool_events) {
              this.messages[assistantIndex].tool_events = [];
            }
            this.messages[assistantIndex].tool_events.push({
              type: "tool_result",
              tool_use_id: event.tool_use_id,
              name: event.name,
              result: event.result || {},
            });
          } else if (event.type === "approval_required") {
            if (event.session_id && !this.currentSessionId) {
              this.currentSessionId = event.session_id;
              this.saveLastSessionId(event.session_id);
            }
            this.attachPendingApproval(assistantIndex, event);
          } else if (event.type === "done") {
            if (event.message) {
              this.messages.splice(assistantIndex, 1, {
                ...event.message,
                streaming: false,
              });
            } else {
              this.messages[assistantIndex].streaming = false;
            }
            if (event.session_id && !this.currentSessionId) {
              this.currentSessionId = event.session_id;
              this.saveLastSessionId(event.session_id);
            }
          } else if (event.type === "error") {
            this.messages[assistantIndex].content =
              `Error: ${event.error || "Failed to send message"}`;
            this.messages[assistantIndex].streaming = false;
          }
        }
        if (!streamed) {
          throw new Error("Empty stream response");
        }
      } catch (err) {
        console.error(err);
        this.messages[assistantIndex].content =
          "Error: Failed to send message. Please check your connection and try again.";
        this.messages[assistantIndex].streaming = false;
      } finally {
        this.loading = false;
      }
    },
    async onSessionSelected(session) {
      try {
        const result = await window.apiService.getChatSessionDetail(
          session.uuid
        );
        if (result.success) {
          this.messages = result.data.messages;
          this.currentSessionId = session.uuid;
          this.saveLastSessionId(session.uuid);
        }
      } catch (error) {
        console.error("Failed to load session:", error);
      }
    },
    startNewChat() {
      this.messages = [];
      this.currentSessionId = null;
      this.saveLastSessionId(null);
    },
    setupResizeListener() {
      this.resizeHandler = this.handleMouseMove.bind(this);
      this.stopResizeHandler = this.stopResize.bind(this);
    },
    removeResizeListener() {
      document.removeEventListener("mousemove", this.resizeHandler);
      document.removeEventListener("mouseup", this.stopResizeHandler);
    },
    startResize(e) {
      this.isResizing = true;
      this.startX = e.clientX;
      this.startWidth = this.width;
      document.addEventListener("mousemove", this.resizeHandler);
      document.addEventListener("mouseup", this.stopResizeHandler);
      e.preventDefault();
    },
    handleMouseMove(e) {
      if (!this.isResizing) return;
      const deltaX = this.startX - e.clientX; // Reversed for right sidebar
      const newWidth = this.startWidth + deltaX;

      // On mobile (768px or less), limit width to 90% of viewport
      const isMobile = window.innerWidth <= 768;
      const effectiveMaxWidth = isMobile
        ? window.innerWidth * 0.9
        : this.maxWidth;

      if (newWidth >= this.minWidth && newWidth <= effectiveMaxWidth) {
        this.width = newWidth;
      }
    },
    stopResize() {
      this.isResizing = false;
      document.removeEventListener("mousemove", this.resizeHandler);
      document.removeEventListener("mouseup", this.stopResizeHandler);
      this.saveWidth(); // Save width when resize is finished
    },
    handleKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
      // Shift+Enter will naturally create a newline (default behavior)
    },
    scrollToBottom() {
      this.$nextTick(() => {
        const messagesContainer = this.$el.querySelector(".messages");
        if (messagesContainer && this.messages.length > 0) {
          const messageElements = messagesContainer.querySelectorAll(
            ".message-bubble:not(.loading)"
          );
          if (messageElements.length > 0) {
            const lastMessage = messageElements[messageElements.length - 1];
            lastMessage.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
          }
        }
      });
    },
    formatTimestamp(timestamp) {
      if (!timestamp) return "";
      const date = new Date(timestamp);
      const now = new Date();
      const isToday = date.toDateString() === now.toDateString();

      if (isToday) {
        // Show only time for today's messages
        return date.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });
      } else {
        // Show date and time for older messages
        return (
          date.toLocaleDateString() +
          " " +
          date.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        );
      }
    },

    async loadAISettings() {
      try {
        const result = await window.apiService.getAISettings();
        if (result.success) {
          this.aiSettings = result.data;
          this.selectedModel = result.data.current_model;

          // If no current model or it's not available, pick the first available one
          if (
            !this.selectedModel ||
            !this.isModelAvailable(this.selectedModel)
          ) {
            const availableModels = this.getAvailableModels();
            if (availableModels.length > 0) {
              this.selectedModel = availableModels[0].value;
            }
          }
        }
      } catch (error) {
        console.error("Failed to load AI settings:", error);
      }
    },

    async loadLastChatSession() {
      // Only load if we don't already have messages and no current session
      if (this.messages.length > 0 || this.currentSessionId) {
        return;
      }

      const lastSessionId = this.loadLastSessionId();
      if (!lastSessionId) {
        return;
      }

      try {
        // Try to load the session directly, handle 404 gracefully
        const sessionData =
          await window.apiService.getChatSessionDetail(lastSessionId);
        if (sessionData.success) {
          await this.onSessionSelected(sessionData.data);
        }
      } catch (error) {
        // Session no longer exists or other error, clear the stored ID
        this.saveLastSessionId(null);
        console.error("Failed to load last chat session:", error);
      }
    },

    isModelAvailable(modelName) {
      const availableModels = this.getAvailableModels();
      return availableModels.some((model) => model.value === modelName);
    },

    toggleModelSelector() {
      this.showModelSelector = !this.showModelSelector;

      if (this.showModelSelector) {
        // Check if dropdown would be cut off and position accordingly
        this.$nextTick(() => {
          const dropdown = this.$el.querySelector(".model-dropdown");
          const button = this.$el.querySelector(".model-selector-btn");

          if (dropdown && button) {
            const buttonRect = button.getBoundingClientRect();
            const viewportHeight = window.innerHeight;
            const dropdownHeight = Math.min(
              300,
              this.getAvailableModels().length * 40
            ); // estimated height

            // If there's not enough space below, show above
            if (buttonRect.bottom + dropdownHeight > viewportHeight - 20) {
              dropdown.classList.add("show-above");
            } else {
              dropdown.classList.remove("show-above");
            }
          }
        });
      }
    },

    getAvailableModels() {
      if (!this.aiSettings) return [];

      // Return all enabled models from providers with API keys
      const allModels = [];
      Object.keys(this.aiSettings.provider_configs).forEach((providerName) => {
        const config = this.aiSettings.provider_configs[providerName];
        if (config.has_api_key && config.enabled_models) {
          config.enabled_models.forEach((model) => {
            allModels.push({
              value: model,
              label: `${providerName}: ${model}`,
              provider: providerName,
            });
          });
        }
      });

      return allModels;
    },

    getCurrentModelLabel() {
      if (!this.aiSettings) return "Loading...";

      const allModels = this.getAvailableModels();
      if (allModels.length === 0) return "No models available";

      if (!this.selectedModel) return "Select model";

      const currentModel = allModels.find(
        (model) => model.value === this.selectedModel
      );

      return currentModel ? currentModel.label : this.selectedModel;
    },

    async selectModel(modelData) {
      try {
        this.selectedModel = modelData.value;
        this.showModelSelector = false;

        // Update user's default model with the correct provider
        const updateData = {
          provider: modelData.provider,
          model: modelData.value,
        };

        await window.apiService.updateAISettings(updateData);
        await this.loadAISettings(); // Refresh settings
      } catch (error) {
        console.error("Failed to update model:", error);
      }
    },

    openSettings() {
      // Emit event to parent to open settings modal with AI tab
      this.$emit("open-settings", "ai");
    },

    // Context management methods
    toggleContextArea() {
      this.showContextArea = !this.showContextArea;
    },

    removeContextBlock(blockId) {
      this.$emit("remove-context-block", blockId);
    },

    clearAllContext() {
      this.$emit("clear-context");
    },

    getContextPreview(block) {
      return block.content.length > 50
        ? block.content.substring(0, 50) + "..."
        : block.content;
    },

    getContextCount() {
      return this.chatContextBlocks.length;
    },

    hasContext() {
      return this.chatContextBlocks.length > 0;
    },

    parseMarkdown(content) {
      if (!content) return "";

      // Configure marked options
      marked.setOptions({
        breaks: true,
        gfm: true,
      });

      // Parse markdown to HTML
      const html = marked.parse(content);

      // Sanitize HTML to prevent XSS
      const cleanHtml = DOMPurify.sanitize(html);

      return cleanHtml;
    },

    highlightCode() {
      // Apply syntax highlighting after DOM update
      this.$nextTick(() => {
        const codeBlocks = this.$el.querySelectorAll("pre code");
        codeBlocks.forEach((block) => {
          Prism.highlightElement(block);
        });
        this.addCopyButtons();
      });
    },

    addCopyButtons() {
      // Add copy buttons to code blocks
      const preElements = this.$el.querySelectorAll(".message-content pre");
      preElements.forEach((pre) => {
        // Skip if copy button already exists
        if (pre.querySelector(".copy-button")) return;

        // Wrap pre element in container if not already wrapped
        if (!pre.parentElement.classList.contains("code-block-container")) {
          const container = document.createElement("div");
          container.className = "code-block-container";
          pre.parentNode.insertBefore(container, pre);
          container.appendChild(pre);
        }

        // Create copy button
        const copyButton = document.createElement("button");
        copyButton.className = "copy-button";
        copyButton.textContent = "copy";
        copyButton.addEventListener("click", () =>
          this.copyToClipboard(pre.textContent, copyButton)
        );

        // Add button to container
        pre.parentElement.appendChild(copyButton);
      });
    },

    async copyToClipboard(text, button) {
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "copied!";
        button.classList.add("copied");
        setTimeout(() => {
          button.textContent = "copy";
          button.classList.remove("copied");
        }, 2000);
      } catch (err) {
        // Fallback for browsers that don't support clipboard API
        const textArea = document.createElement("textarea");
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        try {
          document.execCommand("copy");
          button.textContent = "copied!";
          button.classList.add("copied");
          setTimeout(() => {
            button.textContent = "copy";
            button.classList.remove("copied");
          }, 2000);
        } catch (fallbackErr) {
          button.textContent = "failed";
          setTimeout(() => {
            button.textContent = "copy";
          }, 2000);
        }
        document.body.removeChild(textArea);
      }
    },

    toggleThinking(messageIndex) {
      this.expandedThinking = {
        ...this.expandedThinking,
        [messageIndex]: !this.expandedThinking[messageIndex],
      };
    },

    toggleToolCalls(messageIndex) {
      this.expandedToolCalls = {
        ...this.expandedToolCalls,
        [messageIndex]: !this.expandedToolCalls[messageIndex],
      };
    },

    autoExpandToolCalls(messageIndex) {
      // Open the tools strip the first time a tool fires on this message
      // so the user can see what's happening live (especially important
      // with auto-approve, where there's no other surface for tool work).
      // We only flip from undefined → true; an explicit user collapse
      // (false) is preserved.
      if (this.expandedToolCalls[messageIndex] === undefined) {
        this.expandedToolCalls = {
          ...this.expandedToolCalls,
          [messageIndex]: true,
        };
      }
    },

    runningToolName(msg) {
      // Latest tool_use without a matching tool_result is what's "in
      // flight". Used to label the strip header while streaming.
      const events = msg && msg.tool_events ? msg.tool_events : [];
      if (!events.length) return null;
      const seenResults = new Set();
      for (const ev of events) {
        if (ev.type === "tool_result" && ev.tool_use_id) {
          seenResults.add(ev.tool_use_id);
        }
      }
      for (let i = events.length - 1; i >= 0; i--) {
        const ev = events[i];
        if (ev.type === "tool_use" && !seenResults.has(ev.tool_use_id)) {
          return ev.name || "tool";
        }
      }
      return null;
    },

    toggleToolCall(messageIndex, eventIndex) {
      const key = `${messageIndex}:${eventIndex}`;
      this.expandedToolCall = {
        ...this.expandedToolCall,
        [key]: !this.expandedToolCall[key],
      };
    },

    isToolCallExpanded(messageIndex, eventIndex) {
      return !!this.expandedToolCall[`${messageIndex}:${eventIndex}`];
    },

    toolCallPairs(msg) {
      const events = msg && msg.tool_events ? msg.tool_events : [];
      const byId = {};
      const order = [];
      for (const ev of events) {
        if (!ev || !ev.tool_use_id) continue;
        if (!byId[ev.tool_use_id]) {
          byId[ev.tool_use_id] = {
            tool_use_id: ev.tool_use_id,
            name: ev.name || "",
            input: null,
            result: null,
          };
          order.push(ev.tool_use_id);
        }
        if (ev.type === "tool_use") {
          byId[ev.tool_use_id].input = ev.input || {};
          if (ev.name) byId[ev.tool_use_id].name = ev.name;
        } else if (ev.type === "tool_result") {
          byId[ev.tool_use_id].result = ev.result ?? null;
          if (ev.name && !byId[ev.tool_use_id].name)
            byId[ev.tool_use_id].name = ev.name;
        }
      }
      return order.map((id) => byId[id]);
    },

    summarizeToolInput(input) {
      if (!input || typeof input !== "object") return "";
      const entries = Object.entries(input);
      if (!entries.length) return "()";
      const body = entries
        .map(([k, v]) => {
          let display;
          if (typeof v === "string") {
            display =
              v.length > 40
                ? JSON.stringify(v.slice(0, 40)) + "…"
                : JSON.stringify(v);
          } else {
            try {
              display = JSON.stringify(v);
            } catch (_) {
              display = String(v);
            }
            if (display.length > 40) display = display.slice(0, 40) + "…";
          }
          return `${k}=${display}`;
        })
        .join(", ");
      return `(${body})`;
    },

    summarizeToolResult(result) {
      if (result == null) return "…";
      if (typeof result !== "object") return String(result);
      if (result.error) return `error: ${result.error}`;
      if (typeof result.count === "number") {
        return `${result.count} result${result.count === 1 ? "" : "s"}`;
      }
      if (Array.isArray(result.results)) {
        return `${result.results.length} result${result.results.length === 1 ? "" : "s"}`;
      }
      if (result.block || result.page) return "ok";
      return "ok";
    },

    formatToolJson(value) {
      try {
        return JSON.stringify(value, null, 2);
      } catch (_) {
        return String(value);
      }
    },

    attachPendingApproval(assistantIndex, event) {
      const toolUses = event.tool_uses || [];
      const decisions = {};
      for (const tu of toolUses) {
        if (tu.requires_approval) {
          // Default to approve so the user can confirm all with one click,
          // but nothing executes until they submit.
          decisions[tu.tool_use_id] = "approve";
        }
      }
      this.pendingApprovals = {
        ...this.pendingApprovals,
        [assistantIndex]: {
          approval_id: event.approval_id,
          tool_uses: toolUses,
          decisions,
          submitting: false,
          error: null,
        },
      };
      this.messages[assistantIndex].pending_approval_id = event.approval_id;
      this.messages[assistantIndex].streaming = false;
      if (event.partial_text) {
        this.messages[assistantIndex].content = event.partial_text;
      }
      if (event.partial_thinking) {
        this.messages[assistantIndex].thinking = event.partial_thinking;
      }
      if (Array.isArray(event.tool_events) && event.tool_events.length) {
        this.messages[assistantIndex].tool_events = event.tool_events;
      }
    },

    setApprovalDecision(messageIndex, toolUseId, decision) {
      const pa = this.pendingApprovals[messageIndex];
      if (!pa) return;
      this.pendingApprovals = {
        ...this.pendingApprovals,
        [messageIndex]: {
          ...pa,
          decisions: { ...pa.decisions, [toolUseId]: decision },
        },
      };
    },

    getApprovalState(messageIndex) {
      return this.pendingApprovals[messageIndex] || null;
    },

    writeToolUses(pa) {
      if (!pa) return [];
      return (pa.tool_uses || []).filter((tu) => tu.requires_approval);
    },

    async submitApproval(messageIndex) {
      const pa = this.pendingApprovals[messageIndex];
      if (!pa || pa.submitting) return;
      this.pendingApprovals = {
        ...this.pendingApprovals,
        [messageIndex]: { ...pa, submitting: true, error: null },
      };
      this.messages[messageIndex].streaming = true;

      const payload = {
        decisions: pa.decisions,
        // Send the user's CURRENT auto-approve preference so a toggle
        // between the original send and this approval takes effect on
        // any follow-up writes the model emits during resume.
        auto_approve_notes_writes: this.autoApproveActive,
      };
      try {
        for await (const event of window.apiService.resumeApproval(
          pa.approval_id,
          payload
        )) {
          if (event.type === "session") {
            if (event.session_id && !this.currentSessionId) {
              this.currentSessionId = event.session_id;
              this.saveLastSessionId(event.session_id);
            }
          } else if (event.type === "text") {
            this.messages[messageIndex].content =
              (this.messages[messageIndex].content || "") + (event.delta || "");
          } else if (event.type === "thinking") {
            this.messages[messageIndex].thinking =
              (this.messages[messageIndex].thinking || "") +
              (event.delta || "");
          } else if (event.type === "tool_use") {
            if (!this.messages[messageIndex].tool_events) {
              this.messages[messageIndex].tool_events = [];
            }
            this.messages[messageIndex].tool_events.push({
              type: "tool_use",
              tool_use_id: event.tool_use_id,
              name: event.name,
              input: event.input || {},
            });
            this.autoExpandToolCalls(messageIndex);
          } else if (event.type === "tool_result") {
            if (!this.messages[messageIndex].tool_events) {
              this.messages[messageIndex].tool_events = [];
            }
            this.messages[messageIndex].tool_events.push({
              type: "tool_result",
              tool_use_id: event.tool_use_id,
              name: event.name,
              result: event.result || {},
            });
          } else if (event.type === "approval_required") {
            this.attachPendingApproval(messageIndex, event);
            return;
          } else if (event.type === "done") {
            if (event.message) {
              this.messages.splice(messageIndex, 1, {
                ...event.message,
                streaming: false,
              });
            } else {
              this.messages[messageIndex].streaming = false;
            }
            const next = { ...this.pendingApprovals };
            delete next[messageIndex];
            this.pendingApprovals = next;
          } else if (event.type === "error") {
            this.pendingApprovals = {
              ...this.pendingApprovals,
              [messageIndex]: {
                ...this.pendingApprovals[messageIndex],
                submitting: false,
                error: event.error || "Failed to resume",
              },
            };
            this.messages[messageIndex].streaming = false;
            return;
          }
        }
      } catch (err) {
        console.error(err);
        this.pendingApprovals = {
          ...this.pendingApprovals,
          [messageIndex]: {
            ...this.pendingApprovals[messageIndex],
            submitting: false,
            error: "Failed to resume approval.",
          },
        };
        this.messages[messageIndex].streaming = false;
      }
    },

    rejectAllApproval(messageIndex) {
      const pa = this.pendingApprovals[messageIndex];
      if (!pa) return;
      const decisions = { ...pa.decisions };
      for (const tu of pa.tool_uses || []) {
        if (tu.requires_approval) {
          decisions[tu.tool_use_id] = "reject";
        }
      }
      this.pendingApprovals = {
        ...this.pendingApprovals,
        [messageIndex]: { ...pa, decisions },
      };
      this.submitApproval(messageIndex);
    },

    formatTokens(n) {
      if (n == null) return "0";
      if (n >= 1000) return (n / 1000).toFixed(1) + "k";
      return String(n);
    },

    formatUsage(usage) {
      if (!usage) return "";
      const input = usage.input_tokens || 0;
      const output = usage.output_tokens || 0;
      const cacheRead = usage.cache_read_input_tokens || 0;
      const cacheCreation = usage.cache_creation_input_tokens || 0;
      const parts = [
        `in ${this.formatTokens(input + cacheRead + cacheCreation)}`,
        `out ${this.formatTokens(output)}`,
      ];
      const totalInput = input + cacheRead + cacheCreation;
      if (totalInput > 0 && cacheRead > 0) {
        const pct = Math.round((cacheRead / totalInput) * 100);
        parts.push(`${pct}% cached`);
      }
      return parts.join(" · ");
    },

    hasUsage(usage) {
      if (!usage) return false;
      return (
        (usage.input_tokens != null && usage.input_tokens > 0) ||
        (usage.output_tokens != null && usage.output_tokens > 0) ||
        (usage.cache_read_input_tokens != null &&
          usage.cache_read_input_tokens > 0)
      );
    },

    // Message menu methods
    toggleMessageMenu(messageIndex) {
      // Close all other menus first
      const newMenus = {};
      newMenus[messageIndex] = !this.messageMenus[messageIndex];
      this.messageMenus = newMenus;
    },

    closeAllMessageMenus() {
      this.messageMenus = {};
    },

    setupDocumentListener() {
      this.documentClickHandler = this.handleDocumentClick.bind(this);
      document.addEventListener("click", this.documentClickHandler);
    },

    removeDocumentListener() {
      if (this.documentClickHandler) {
        document.removeEventListener("click", this.documentClickHandler);
      }
    },

    handleDocumentClick(event) {
      const messageMenuContainer = event.target.closest(
        ".message-menu-container"
      );
      if (!messageMenuContainer) {
        this.closeAllMessageMenus();
      }
    },

    async copyMessageContent(message, messageIndex) {
      try {
        await navigator.clipboard.writeText(message.content);
        // Close menu after copying
        this.closeAllMessageMenus();

        // Show temporary feedback (could be enhanced with a toast notification)
        console.log("Message copied to clipboard");
      } catch (err) {
        // Fallback for browsers that don't support clipboard API
        const textArea = document.createElement("textarea");
        textArea.value = message.content;
        document.body.appendChild(textArea);
        textArea.select();
        try {
          document.execCommand("copy");
          this.closeAllMessageMenus();
          console.log("Message copied to clipboard");
        } catch (fallbackErr) {
          console.error("Failed to copy message:", fallbackErr);
        }
        document.body.removeChild(textArea);
      }
    },

    // Click outside to close panel
    setupClickOutsideListener() {
      this.clickOutsideHandler = (e) => {
        // Close the tools popover when clicking anywhere outside it.
        // Clicks on menu items (inside .tools-container) are allowed so
        // users can flip multiple toggles in one session.
        if (this.showToolsMenu && !e.target.closest(".tools-container")) {
          this.showToolsMenu = false;
        }

        // Only close if panel is open and click is outside the panel
        if (this.isOpen && !this.$el.contains(e.target)) {
          // Check if click is within the history dropdown (teleported content)
          const historyDropdown = e.target.closest(".history-dropdown");
          if (historyDropdown) {
            return; // Don't close if clicking within history dropdown
          }

          // Check if click is within the model dropdown
          const modelDropdown = e.target.closest(".model-dropdown");
          if (modelDropdown) {
            return; // Don't close if clicking within model dropdown
          }

          this.isOpen = false;
          this.saveOpenState();
        }
      };
      document.addEventListener("click", this.clickOutsideHandler);
    },

    removeClickOutsideListener() {
      if (this.clickOutsideHandler) {
        document.removeEventListener("click", this.clickOutsideHandler);
      }
    },
  },
  template: `
    <div class="chat-panel" :class="{ open: isOpen }" :style="isOpen ? { width: width + 'px' } : {}">
      <div class="chat-resize-handle" 
           :class="{ resizing: isResizing }"
           @mousedown="startResize">
      </div>
      <button class="chat-toggle" @click="togglePanel">ai</button>
      <div class="chat-content">
        <div class="chat-header">
          <ChatHistory @session-selected="onSessionSelected" />
          <button class="new-chat-btn" @click="startNewChat" title="Start new chat">+</button>
        </div>
        <div class="messages">
          <div v-for="(msg, index) in messages" :key="index" :class="['message-bubble', msg.role]">
            <div v-if="msg.role === 'assistant' && msg.thinking" class="thinking-block">
              <button class="thinking-toggle" @click="toggleThinking(index)">
                {{ expandedThinking[index] ? '▾' : '▸' }} thinking
              </button>
              <div v-if="expandedThinking[index]" class="thinking-content" v-html="parseMarkdown(msg.thinking)"></div>
            </div>
            <div v-if="msg.role === 'assistant' && toolCallPairs(msg).length" class="tool-calls-block" :class="{ 'tool-calls-running': msg.streaming && runningToolName(msg) }">
              <button class="tool-calls-toggle" @click="toggleToolCalls(index)">
                {{ expandedToolCalls[index] ? '▾' : '▸' }}
                <template v-if="msg.streaming && runningToolName(msg)">
                  <span class="tool-calls-running-dot"></span>
                  running {{ runningToolName(msg) }}…
                </template>
                <template v-else>
                  tools ({{ toolCallPairs(msg).length }})
                </template>
              </button>
              <div v-if="expandedToolCalls[index]" class="tool-calls-list">
                <div
                  v-for="(call, callIndex) in toolCallPairs(msg)"
                  :key="call.tool_use_id"
                  class="tool-call"
                >
                  <button class="tool-call-summary" @click="toggleToolCall(index, callIndex)">
                    <span class="tool-call-chevron">{{ isToolCallExpanded(index, callIndex) ? '▾' : '▸' }}</span>
                    <span class="tool-call-name">{{ call.name }}</span>
                    <span class="tool-call-args">{{ summarizeToolInput(call.input) }}</span>
                    <span class="tool-call-arrow">→</span>
                    <span class="tool-call-result-summary" v-if="call.result !== null">
                      {{ summarizeToolResult(call.result) }}
                    </span>
                    <span class="tool-call-result-summary pending" v-else>running…</span>
                  </button>
                  <div v-if="isToolCallExpanded(index, callIndex)" class="tool-call-details">
                    <div class="tool-call-detail-label">input</div>
                    <pre class="tool-call-detail-body">{{ formatToolJson(call.input) }}</pre>
                    <template v-if="call.result !== null">
                      <div class="tool-call-detail-label">result</div>
                      <pre class="tool-call-detail-body">{{ formatToolJson(call.result) }}</pre>
                    </template>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="msg.role === 'assistant' && getApprovalState(index)" class="approval-block">
              <div class="approval-header">
                ⚠ Assistant wants to make changes to your notes. Review and approve:
              </div>
              <div
                v-for="tu in writeToolUses(getApprovalState(index))"
                :key="tu.tool_use_id"
                class="approval-tool-call"
              >
                <div class="approval-tool-head">
                  <span class="approval-tool-name">{{ tu.name }}</span>
                  <span class="approval-tool-args">{{ summarizeToolInput(tu.input) }}</span>
                </div>
                <pre class="approval-tool-body">{{ formatToolJson(tu.input) }}</pre>
                <div class="approval-tool-actions">
                  <label class="approval-choice">
                    <input
                      type="radio"
                      :name="'approval-' + index + '-' + tu.tool_use_id"
                      :checked="getApprovalState(index).decisions[tu.tool_use_id] === 'approve'"
                      @change="setApprovalDecision(index, tu.tool_use_id, 'approve')"
                    />
                    approve
                  </label>
                  <label class="approval-choice">
                    <input
                      type="radio"
                      :name="'approval-' + index + '-' + tu.tool_use_id"
                      :checked="getApprovalState(index).decisions[tu.tool_use_id] === 'reject'"
                      @change="setApprovalDecision(index, tu.tool_use_id, 'reject')"
                    />
                    reject
                  </label>
                </div>
              </div>
              <div v-if="getApprovalState(index).error" class="approval-error">
                {{ getApprovalState(index).error }}
              </div>
              <div class="approval-footer">
                <button
                  class="approval-submit"
                  @click="submitApproval(index)"
                  :disabled="getApprovalState(index).submitting"
                >
                  {{ getApprovalState(index).submitting ? 'applying…' : 'apply decisions' }}
                </button>
                <button
                  class="approval-reject-all"
                  @click="rejectAllApproval(index)"
                  :disabled="getApprovalState(index).submitting"
                >
                  reject all
                </button>
              </div>
            </div>
            <div v-if="msg.role === 'assistant' && msg.streaming && !msg.content" class="message-content loading-content">
              <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
            <div v-else class="message-content" v-html="parseMarkdown(msg.content)"></div>
            <div class="message-footer">
              <div class="message-timestamp">
                {{ formatTimestamp(msg.created_at) }}
                <span v-if="msg.role === 'assistant' && msg.ai_model" class="model-info">
                  · {{ msg.ai_model.display_name || msg.ai_model.name }}
                </span>
                <span v-if="msg.role === 'assistant' && hasUsage(msg.usage)" class="usage-info" :title="'Token usage'">
                  · {{ formatUsage(msg.usage) }}
                </span>
              </div>
              <div class="message-menu-container" v-if="msg.role === 'assistant'">
                <button
                  @click="toggleMessageMenu(index)"
                  class="message-menu-btn"
                  title="Message options"
                >
                  ⋮
                </button>
                <div v-if="messageMenus[index]" class="message-menu" @click.stop>
                  <button
                    @click="copyMessageContent(msg, index)"
                    class="message-menu-item"
                  >
                    copy message
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- Context Area -->
        <div class="context-area" v-if="hasContext() || showContextArea">
          <div class="context-header">
            <span class="context-title">
              Context ({{ getContextCount() }})
            </span>
            <div class="context-actions">
              <button 
                v-if="hasContext()" 
                @click="clearAllContext" 
                class="context-clear-btn" 
                title="Clear all context"
              >
                ✕
              </button>
            </div>
          </div>
          <div class="context-blocks" v-if="hasContext()">
            <div 
              v-for="block in chatContextBlocks" 
              :key="block.uuid" 
              class="context-block"
            >
              <div class="context-block-content">
                {{ getContextPreview(block) }}
              </div>
              <button 
                @click="removeContextBlock(block.uuid)" 
                class="context-block-remove"
                title="Remove from context"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
        
        <div class="input-area">
          <div v-if="hasSessionStats" class="session-stats" title="Session token usage">
            <span>{{ sessionStats.turns }} turn{{ sessionStats.turns === 1 ? '' : 's' }}</span>
            <span class="session-stats-sep">·</span>
            <span>in {{ formatTokens(sessionStats.totalInput) }}</span>
            <span class="session-stats-sep">·</span>
            <span>out {{ formatTokens(sessionStats.outputTokens) }}</span>
            <template v-if="sessionStats.cacheRead > 0">
              <span class="session-stats-sep">·</span>
              <span>{{ Math.round(sessionStats.cacheRatio * 100) }}% cached</span>
            </template>
          </div>
          <div class="chat-controls">
            <div class="model-selector" v-if="aiSettings">
              <button 
                class="model-selector-btn" 
                @click="toggleModelSelector"
                :title="getCurrentModelLabel()"
              >
                {{ getCurrentModelLabel() }}
                <span class="dropdown-arrow">▼</span>
              </button>
              <div v-if="showModelSelector" class="model-dropdown">
                <div v-if="getAvailableModels().length === 0" class="model-option disabled">
                  No models available. Configure API keys in settings.
                </div>
                <div 
                  v-else
                  v-for="model in getAvailableModels()" 
                  :key="model.value"
                  class="model-option"
                  :class="{ active: model.value === selectedModel }"
                  @click="selectModel(model)"
                >
                  {{ model.label }}
                </div>
              </div>
            </div>
            <button
              class="context-btn"
              @click="toggleContextArea"
              :class="{ active: hasContext() }"
              :title="hasContext() ? 'Context (' + getContextCount() + ')' : 'Add context'"
            >
              ctx
            </button>
            <div class="tools-container">
              <button
                class="tools-btn"
                @click="toggleToolsMenu"
                :class="{ active: hasActiveTools, 'auto-approve-warning': autoApproveActive }"
                :title="autoApproveActive ? 'Tools — AUTO-APPROVE WRITES is on; the assistant can edit your notes without confirmation' : (hasActiveTools ? 'Tools (some active)' : 'Tools')"
              >
                <span v-if="autoApproveActive" class="tools-btn-warning-glyph">⚠</span>
                tools
              </button>
              <div v-if="showToolsMenu" class="tools-menu">
                <label class="tools-menu-item">
                  <input
                    type="checkbox"
                    :checked="enableNotesTools"
                    @change="toggleNotesTools"
                  />
                  <span class="tools-menu-label">
                    <span class="tools-menu-name">search notes</span>
                    <span class="tools-menu-hint">Let the assistant search your notes (Anthropic only).</span>
                  </span>
                </label>
                <label class="tools-menu-item">
                  <input
                    type="checkbox"
                    :checked="enableNotesWriteTools"
                    @change="toggleNotesWriteTools"
                  />
                  <span class="tools-menu-label">
                    <span class="tools-menu-name">edit notes</span>
                    <span class="tools-menu-hint">Let the assistant create, edit, and move notes. Every write pauses for your approval (Anthropic only).</span>
                  </span>
                </label>
                <label
                  class="tools-menu-item"
                  :class="{ disabled: !enableNotesWriteTools }"
                >
                  <input
                    type="checkbox"
                    :checked="autoApproveNotesWrites"
                    :disabled="!enableNotesWriteTools"
                    @change="toggleAutoApproveNotesWrites"
                  />
                  <span class="tools-menu-label">
                    <span class="tools-menu-name">auto-approve writes</span>
                    <span class="tools-menu-hint">⚠ Skip the per-call approval gate — writes execute immediately. Only takes effect when "edit notes" is on.</span>
                  </span>
                </label>
                <label class="tools-menu-item">
                  <input
                    type="checkbox"
                    :checked="enableWebSearch"
                    @change="toggleWebSearch"
                  />
                  <span class="tools-menu-label">
                    <span class="tools-menu-name">web search</span>
                    <span class="tools-menu-hint">Let the assistant query the web. Each turn adds ~600-1500 tokens to the prompt even when unused.</span>
                  </span>
                </label>
              </div>
            </div>
            <button class="settings-btn" @click="openSettings" title="AI Settings">cfg</button>
          </div>
          <div class="message-input">
            <textarea v-model="message" placeholder="ask something..." @keydown="handleKeydown"></textarea>
            <button @click="sendMessage" :disabled="loading">
              {{ loading ? 'sending...' : 'send' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
};

window.ChatPanel = ChatPanel;
