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
      };
      this.message = "";
      this.loading = true;
      try {
        const result = await window.apiService.sendAIMessage(payload);
        if (result.success) {
          // Use the complete message data from the API response
          if (result.data.message) {
            this.messages.push(result.data.message);
          } else {
            // Fallback for backward compatibility
            this.messages.push({
              role: "assistant",
              content: result.data.response,
              created_at: new Date().toISOString(),
            });
          }
          if (result.data.session_id && !this.currentSessionId) {
            this.currentSessionId = result.data.session_id;
            this.saveLastSessionId(result.data.session_id);
          }
        } else {
          // Handle error response
          const errorMsg = result.error || "Failed to send message";
          this.messages.push({
            role: "assistant",
            content: `Error: ${errorMsg}`,
            created_at: new Date().toISOString(),
          });
        }
      } catch (err) {
        console.error(err);
        this.messages.push({
          role: "assistant",
          content:
            "Error: Failed to send message. Please check your connection and try again.",
          created_at: new Date().toISOString(),
        });
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

    formatUsage(usage) {
      if (!usage) return "";
      const parts = [];
      if (usage.input_tokens != null) parts.push(`in ${usage.input_tokens}`);
      if (usage.output_tokens != null) parts.push(`out ${usage.output_tokens}`);
      const cached = usage.cache_read_input_tokens || 0;
      if (cached > 0) parts.push(`cached ${cached}`);
      return parts.join(" · ");
    },

    hasUsage(usage) {
      if (!usage) return false;
      return (
        (usage.input_tokens != null && usage.input_tokens > 0) ||
        (usage.output_tokens != null && usage.output_tokens > 0)
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
            <div class="message-content" v-html="parseMarkdown(msg.content)"></div>
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
          <div v-if="loading" class="message-bubble assistant loading">
            <div class="message-content loading-content">
              <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
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
