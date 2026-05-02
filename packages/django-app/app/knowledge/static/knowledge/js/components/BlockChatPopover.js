// Block AI Chat Popover — open a fresh AI chat focused on the current block.
//
// Triggered by Cmd/Ctrl+Shift+, on a focused block (or via the block ⋮ menu).
// The block is preloaded as chat context (text + image asset, if any), the
// user types a one-shot prompt, and the assistant streams back a response
// directly into the popover. Notes write tools are enabled by default with
// auto-approve so the assistant can drop the result as nested blocks under
// the source block without a second click — that's the common flow ("estimate
// macros from this photo and save them as sub-blocks").
//
// Each open starts a brand-new chat session — distinct from the persistent
// ChatPanel sidebar, which carries history across turns. Closing the popover
// drops the session reference.
//
// Emits:
//   close — user dismissed (Esc, backdrop, "done" button)

window.BlockChatPopover = {
  name: "BlockChatPopover",
  props: {
    isOpen: { type: Boolean, default: false },
    block: { type: Object, default: null },
  },
  emits: ["close"],
  data() {
    return {
      message: "",
      messages: [],
      loading: false,
      currentSessionId: null,
      aiSettings: null,
      selectedModel: null,
      showModelSelector: false,
      // Default tools ON — the popover's whole point is to land results
      // back under the source block. Without write tools the assistant
      // can only narrate, which defeats the purpose. Persisted so a user
      // who turned them off doesn't have to re-disable each time.
      enableNotesWriteTools: this.loadPref(
        "blockChatPopover.enableNotesWriteTools",
        true
      ),
      autoApproveNotesWrites: this.loadPref(
        "blockChatPopover.autoApproveNotesWrites",
        true
      ),
      enableNotesTools: this.loadPref(
        "blockChatPopover.enableNotesTools",
        false
      ),
      enableWebSearch: this.loadPref("blockChatPopover.enableWebSearch", false),
      // Auto-instruct the assistant to nest its output under the source
      // block. When off, the assistant is just told the source uuid and
      // can decide what to do (or do nothing useful at all).
      nestUnderBlock: this.loadPref("blockChatPopover.nestUnderBlock", true),
      showToolsMenu: false,
      pendingApprovals: {},
    };
  },
  computed: {
    blockPreviewText() {
      const content = (this.block?.content || "").trim();
      if (!content) {
        if (this.block?.asset?.original_filename) {
          return `[image: ${this.block.asset.original_filename}]`;
        }
        return "[empty block]";
      }
      return content.length > 220 ? content.slice(0, 220) + "…" : content;
    },
    blockHasImage() {
      return !!(this.block?.asset && this.block.asset.file_type === "image");
    },
    blockImageUrl() {
      if (!this.blockHasImage) return "";
      return window.apiService.assetServeUrl(this.block.asset.uuid);
    },
    hasActiveTools() {
      return (
        this.enableNotesTools ||
        this.enableNotesWriteTools ||
        this.enableWebSearch
      );
    },
    autoApproveActive() {
      return this.enableNotesWriteTools && this.autoApproveNotesWrites;
    },
    hasResponse() {
      return this.messages.length > 0;
    },
  },
  watch: {
    isOpen: {
      handler(open) {
        if (!open) return;
        // Each open is a fresh chat — toss any prior turn so the popover
        // doesn't visually leak between two unrelated blocks.
        this.message = "";
        this.messages = [];
        this.currentSessionId = null;
        this.pendingApprovals = {};
        this.loading = false;
        this.showModelSelector = false;
        this.showToolsMenu = false;
        if (!this.aiSettings) {
          this.loadAISettings();
        }
        this.$nextTick(() => {
          const ta = this.$refs.messageInput;
          if (ta && typeof ta.focus === "function") ta.focus();
        });
      },
      immediate: true,
    },
  },
  methods: {
    loadPref(key, defaultValue) {
      const saved = localStorage.getItem(key);
      if (saved === null) return defaultValue;
      try {
        return JSON.parse(saved);
      } catch (_) {
        return defaultValue;
      }
    },
    savePref(key, value) {
      localStorage.setItem(key, JSON.stringify(value));
    },
    toggleNotesTools() {
      this.enableNotesTools = !this.enableNotesTools;
      this.savePref("blockChatPopover.enableNotesTools", this.enableNotesTools);
    },
    toggleNotesWriteTools() {
      this.enableNotesWriteTools = !this.enableNotesWriteTools;
      this.savePref(
        "blockChatPopover.enableNotesWriteTools",
        this.enableNotesWriteTools
      );
      // Auto-approve only matters when writes are on; keep state coherent.
      if (!this.enableNotesWriteTools && this.autoApproveNotesWrites) {
        this.autoApproveNotesWrites = false;
        this.savePref("blockChatPopover.autoApproveNotesWrites", false);
      }
    },
    toggleAutoApprove() {
      this.autoApproveNotesWrites = !this.autoApproveNotesWrites;
      this.savePref(
        "blockChatPopover.autoApproveNotesWrites",
        this.autoApproveNotesWrites
      );
    },
    toggleWebSearch() {
      this.enableWebSearch = !this.enableWebSearch;
      this.savePref("blockChatPopover.enableWebSearch", this.enableWebSearch);
    },
    toggleNestUnderBlock() {
      this.nestUnderBlock = !this.nestUnderBlock;
      this.savePref("blockChatPopover.nestUnderBlock", this.nestUnderBlock);
    },
    toggleToolsMenu() {
      this.showToolsMenu = !this.showToolsMenu;
    },
    toggleModelSelector() {
      this.showModelSelector = !this.showModelSelector;
    },
    async loadAISettings() {
      try {
        const result = await window.apiService.getAISettings();
        if (result.success) {
          this.aiSettings = result.data;
          this.selectedModel = result.data.current_model;
          if (
            !this.selectedModel ||
            !this.isModelAvailable(this.selectedModel)
          ) {
            const available = this.getAvailableModels();
            if (available.length > 0) this.selectedModel = available[0].value;
          }
        }
      } catch (error) {
        console.error("Failed to load AI settings:", error);
      }
    },
    isModelAvailable(modelName) {
      return this.getAvailableModels().some((m) => m.value === modelName);
    },
    getAvailableModels() {
      if (!this.aiSettings) return [];
      const all = [];
      Object.keys(this.aiSettings.provider_configs).forEach((providerName) => {
        const config = this.aiSettings.provider_configs[providerName];
        if (config.has_api_key && config.enabled_models) {
          config.enabled_models.forEach((model) => {
            all.push({
              value: model,
              label: `${providerName}: ${model}`,
              provider: providerName,
            });
          });
        }
      });
      return all;
    },
    getCurrentModelLabel() {
      if (!this.aiSettings) return "loading...";
      const all = this.getAvailableModels();
      if (all.length === 0) return "no models available";
      if (!this.selectedModel) return "select model";
      const cur = all.find((m) => m.value === this.selectedModel);
      return cur ? cur.label : this.selectedModel;
    },
    selectModel(modelData) {
      this.selectedModel = modelData.value;
      this.showModelSelector = false;
    },
    buildContextBlock() {
      // Mirror the shape KnowledgeApp.addBlockToContext stores so the
      // backend's _format_message_with_context emits the same `[block X
      // on page Y]` marker — that's what tells the AI which block to
      // nest under when write tools fire.
      if (!this.block) return null;
      return {
        uuid: this.block.uuid,
        content: this.block.content || "",
        block_type: this.block.block_type || "bullet",
        created_at: this.block.created_at || null,
        parent_uuid: this.block.parent_uuid || null,
        page_uuid: this.block.page_uuid || null,
        asset: this.block.asset || null,
      };
    },
    composeUserMessage() {
      const base = (this.message || "").trim();
      if (!this.nestUnderBlock || !this.block?.uuid) return base;
      // Append (don't prepend) the nesting hint — the user's intent
      // reads first, the directive is a tail-note. Including the uuid
      // explicitly removes any ambiguity when there are sibling blocks
      // also referenced via search tools.
      const directive =
        `\n\nWhen you write your answer, use the create_block tool to` +
        ` save the result as one or more nested blocks under the` +
        ` referenced block (parent_uuid=${this.block.uuid}).`;
      return base ? base + directive : directive.trimStart();
    },
    async sendMessage() {
      if (!this.block) return;
      if (!this.message.trim()) return;
      if (!this.selectedModel) {
        this.messages.push({
          role: "assistant",
          content:
            "error: no AI model selected. configure an API key in settings, then try again.",
          created_at: new Date().toISOString(),
        });
        return;
      }
      const ctxBlock = this.buildContextBlock();
      const composed = this.composeUserMessage();

      // The backend reads image bytes from message attachments (driven
      // by asset_uuids), not from context_blocks[].asset. Without this,
      // the model only sees the filename marker and starts guessing.
      const contextImageUuids =
        ctxBlock?.asset?.file_type === "image" && ctxBlock.asset.uuid
          ? [ctxBlock.asset.uuid]
          : [];

      const userMsg = {
        role: "user",
        content: this.message,
        created_at: new Date().toISOString(),
      };
      this.messages.push(userMsg);
      const payload = {
        message: composed,
        model: this.selectedModel,
        session_id: this.currentSessionId,
        context_blocks: ctxBlock ? [ctxBlock] : [],
        enable_notes_tools: this.enableNotesTools,
        enable_notes_write_tools: this.enableNotesWriteTools,
        auto_approve_notes_writes: this.autoApproveActive,
        enable_web_search: this.enableWebSearch,
        asset_uuids: contextImageUuids,
      };
      this.message = "";
      this.loading = true;

      const assistantMsg = {
        role: "assistant",
        content: "",
        thinking: "",
        tool_events: [],
        created_at: new Date().toISOString(),
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
            this.broadcastNotesModified(event.result);
          } else if (event.type === "approval_required") {
            if (event.session_id && !this.currentSessionId) {
              this.currentSessionId = event.session_id;
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
            }
          } else if (event.type === "error") {
            this.messages[assistantIndex].content = `error: ${
              event.error || "failed to send message"
            }`;
            this.messages[assistantIndex].streaming = false;
          }
        }
        if (!streamed) {
          throw new Error("empty stream response");
        }
      } catch (err) {
        console.error(err);
        this.messages[assistantIndex].content =
          "error: failed to send message. check your connection and try again.";
        this.messages[assistantIndex].streaming = false;
      } finally {
        this.loading = false;
      }
    },
    broadcastNotesModified(toolResult) {
      // Same contract as ChatPanel — the parent Page listens and reloads
      // silently when a write tool touches the page being viewed.
      if (!toolResult || typeof toolResult !== "object") return;
      const pages = toolResult.affected_page_uuids;
      if (!Array.isArray(pages) || !pages.length) return;
      try {
        window.dispatchEvent(
          new CustomEvent("brainspread:notes-modified", {
            detail: { page_uuids: pages.map(String) },
          })
        );
      } catch (err) {
        console.error("Failed to dispatch notes-modified event:", err);
      }
    },
    attachPendingApproval(assistantIndex, event) {
      const toolUses = event.tool_uses || [];
      const decisions = {};
      for (const tu of toolUses) {
        if (tu.requires_approval) {
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
            this.broadcastNotesModified(event.result);
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
                error: event.error || "failed to resume",
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
            error: "failed to resume approval.",
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
        if (tu.requires_approval) decisions[tu.tool_use_id] = "reject";
      }
      this.pendingApprovals = {
        ...this.pendingApprovals,
        [messageIndex]: { ...pa, decisions },
      };
      this.submitApproval(messageIndex);
    },
    parseMarkdown(content) {
      if (!content) return "";
      window.marked.setOptions({ breaks: true, gfm: true });
      const html = window.marked.parse(content);
      return window.DOMPurify.sanitize(html);
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
    formatToolJson(value) {
      try {
        return JSON.stringify(value, null, 2);
      } catch (_) {
        return String(value);
      }
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
    handleKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        this.close();
        return;
      }
      if (
        event.key === "Enter" &&
        !event.shiftKey &&
        event.target.tagName === "TEXTAREA"
      ) {
        event.preventDefault();
        if (!this.loading) this.sendMessage();
      }
    },
    handleBackdropClick(event) {
      if (event.target === event.currentTarget) this.close();
    },
    close() {
      this.$emit("close");
    },
  },
  template: `
    <div
      v-if="isOpen"
      class="block-chat-popover-backdrop"
      @click="handleBackdropClick"
      @keydown="handleKeydown"
    >
      <div class="block-chat-popover" role="dialog" aria-label="AI chat for block">
        <div class="block-chat-popover-header">
          <h3 class="block-chat-popover-title">ai chat for block</h3>
          <button
            type="button"
            class="block-chat-popover-close"
            @click="close"
            title="Close (Esc)"
            aria-label="Close"
          >×</button>
        </div>

        <div class="block-chat-popover-source" v-if="block">
          <div class="block-chat-popover-source-label">block in context</div>
          <div class="block-chat-popover-source-body">
            <img
              v-if="blockHasImage"
              :src="blockImageUrl"
              :alt="block.asset.original_filename || ''"
              class="block-chat-popover-source-thumb"
            />
            <div class="block-chat-popover-source-text">{{ blockPreviewText }}</div>
          </div>
        </div>

        <div class="block-chat-popover-messages" v-if="hasResponse">
          <div
            v-for="(msg, index) in messages"
            :key="index"
            :class="['block-chat-popover-msg', msg.role]"
          >
            <div
              v-if="msg.role === 'assistant' && toolCallPairs(msg).length"
              class="block-chat-popover-tools"
            >
              <div class="block-chat-popover-tools-label">
                tools ({{ toolCallPairs(msg).length }})
              </div>
              <div
                v-for="call in toolCallPairs(msg)"
                :key="call.tool_use_id"
                class="block-chat-popover-tool-row"
              >
                <span class="block-chat-popover-tool-name">{{ call.name }}</span>
                <span class="block-chat-popover-tool-args">{{ summarizeToolInput(call.input) }}</span>
                <span class="block-chat-popover-tool-status" v-if="call.result === null">running…</span>
                <span class="block-chat-popover-tool-status ok" v-else-if="!call.result.error">ok</span>
                <span class="block-chat-popover-tool-status err" v-else>err</span>
              </div>
            </div>
            <div
              v-if="msg.role === 'assistant' && getApprovalState(index)"
              class="block-chat-popover-approval"
            >
              <div class="block-chat-popover-approval-head">
                ⚠ assistant wants to write to your notes. review and approve:
              </div>
              <div
                v-for="tu in writeToolUses(getApprovalState(index))"
                :key="tu.tool_use_id"
                class="block-chat-popover-approval-row"
              >
                <div class="block-chat-popover-approval-summary">
                  <span class="block-chat-popover-approval-name">{{ tu.name }}</span>
                  <span class="block-chat-popover-approval-args">{{ summarizeToolInput(tu.input) }}</span>
                </div>
                <pre class="block-chat-popover-approval-body">{{ formatToolJson(tu.input) }}</pre>
                <div class="block-chat-popover-approval-choices">
                  <label>
                    <input
                      type="radio"
                      :name="'bcp-approval-' + index + '-' + tu.tool_use_id"
                      :checked="getApprovalState(index).decisions[tu.tool_use_id] === 'approve'"
                      @change="setApprovalDecision(index, tu.tool_use_id, 'approve')"
                    /> approve
                  </label>
                  <label>
                    <input
                      type="radio"
                      :name="'bcp-approval-' + index + '-' + tu.tool_use_id"
                      :checked="getApprovalState(index).decisions[tu.tool_use_id] === 'reject'"
                      @change="setApprovalDecision(index, tu.tool_use_id, 'reject')"
                    /> reject
                  </label>
                </div>
              </div>
              <div
                v-if="getApprovalState(index).error"
                class="block-chat-popover-approval-error"
              >{{ getApprovalState(index).error }}</div>
              <div class="block-chat-popover-approval-actions">
                <button
                  type="button"
                  class="btn btn-primary"
                  @click="submitApproval(index)"
                  :disabled="getApprovalState(index).submitting"
                >
                  {{ getApprovalState(index).submitting ? 'applying…' : 'apply' }}
                </button>
                <button
                  type="button"
                  class="btn btn-outline"
                  @click="rejectAllApproval(index)"
                  :disabled="getApprovalState(index).submitting"
                >reject all</button>
              </div>
            </div>
            <div
              v-if="msg.role === 'assistant' && msg.streaming && !msg.content"
              class="block-chat-popover-typing"
            >
              <span></span><span></span><span></span>
            </div>
            <div
              v-else
              class="block-chat-popover-content"
              v-html="parseMarkdown(msg.content)"
            ></div>
          </div>
        </div>

        <div class="block-chat-popover-controls">
          <div class="block-chat-popover-model" v-if="aiSettings">
            <button
              type="button"
              class="block-chat-popover-model-btn"
              @click="toggleModelSelector"
              :title="getCurrentModelLabel()"
            >
              {{ getCurrentModelLabel() }} <span class="block-chat-popover-arrow">▼</span>
            </button>
            <div v-if="showModelSelector" class="block-chat-popover-model-dropdown">
              <div
                v-if="getAvailableModels().length === 0"
                class="block-chat-popover-model-option disabled"
              >
                no models. configure API keys in settings.
              </div>
              <div
                v-else
                v-for="model in getAvailableModels()"
                :key="model.value"
                class="block-chat-popover-model-option"
                :class="{ active: model.value === selectedModel }"
                @click="selectModel(model)"
              >{{ model.label }}</div>
            </div>
          </div>
          <div class="block-chat-popover-tools-wrap">
            <button
              type="button"
              class="block-chat-popover-tools-btn"
              :class="{ active: hasActiveTools }"
              @click="toggleToolsMenu"
              :title="autoApproveActive ? 'tools — AUTO-APPROVE WRITES is on; the assistant can edit your notes without confirmation' : 'tools'"
            >
              <span v-if="autoApproveActive" class="block-chat-popover-warn-glyph">⚠</span>
              tools
            </button>
            <div v-if="showToolsMenu" class="block-chat-popover-tools-menu" @click.stop>
              <label class="block-chat-popover-tools-item">
                <input
                  type="checkbox"
                  :checked="enableNotesWriteTools"
                  @change="toggleNotesWriteTools"
                />
                <span>
                  <span class="block-chat-popover-tools-name">edit notes</span>
                  <span class="block-chat-popover-tools-hint">create / edit / move blocks (Anthropic only).</span>
                </span>
              </label>
              <label
                class="block-chat-popover-tools-item"
                :class="{ disabled: !enableNotesWriteTools }"
              >
                <input
                  type="checkbox"
                  :checked="autoApproveNotesWrites"
                  :disabled="!enableNotesWriteTools"
                  @change="toggleAutoApprove"
                />
                <span>
                  <span class="block-chat-popover-tools-name">auto-approve writes</span>
                  <span class="block-chat-popover-tools-hint">⚠ skip the per-call gate.</span>
                </span>
              </label>
              <label class="block-chat-popover-tools-item">
                <input
                  type="checkbox"
                  :checked="enableNotesTools"
                  @change="toggleNotesTools"
                />
                <span>
                  <span class="block-chat-popover-tools-name">search notes</span>
                  <span class="block-chat-popover-tools-hint">read-only search across pages.</span>
                </span>
              </label>
              <label class="block-chat-popover-tools-item">
                <input
                  type="checkbox"
                  :checked="enableWebSearch"
                  @change="toggleWebSearch"
                />
                <span>
                  <span class="block-chat-popover-tools-name">web search</span>
                  <span class="block-chat-popover-tools-hint">let the assistant query the web.</span>
                </span>
              </label>
              <label class="block-chat-popover-tools-item">
                <input
                  type="checkbox"
                  :checked="nestUnderBlock"
                  @change="toggleNestUnderBlock"
                />
                <span>
                  <span class="block-chat-popover-tools-name">nest result under block</span>
                  <span class="block-chat-popover-tools-hint">append a directive telling the assistant to save its answer as nested blocks.</span>
                </span>
              </label>
            </div>
          </div>
        </div>

        <div class="block-chat-popover-input">
          <textarea
            ref="messageInput"
            v-model="message"
            placeholder="ask about this block… (Enter to send, Shift+Enter for newline)"
            :disabled="loading"
          ></textarea>
        </div>

        <div class="block-chat-popover-actions">
          <button
            type="button"
            class="btn btn-outline"
            @click="close"
          >done</button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="loading || !message.trim() || !selectedModel"
            @click="sendMessage"
          >{{ loading ? 'sending…' : 'send' }}</button>
        </div>
      </div>
    </div>
  `,
};
