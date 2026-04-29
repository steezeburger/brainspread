// Help Modal Component
window.HelpModal = {
  props: {
    isOpen: {
      type: Boolean,
      default: false,
    },
  },

  emits: ["close"],

  watch: {
    isOpen(newValue) {
      if (newValue) {
        this.$nextTick(() => {
          const body = this.$refs.modalBody;
          if (body) body.focus();
        });
      }
    },
  },

  methods: {
    handleModalKeydown(event) {
      if (event.key === "Escape") {
        this.$emit("close");
        return;
      }
      if (event.key === "Tab") {
        const modal = this.$el?.querySelector(".settings-modal-content");
        if (!modal) return;
        const focusable = Array.from(
          modal.querySelectorAll(
            'button:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        );
        if (focusable.length < 2) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    },
  },

  template: `
    <div v-if="isOpen" class="settings-modal" @click.self="$emit('close')" @keydown="handleModalKeydown">
      <div class="settings-modal-content help-modal-content">
        <div class="help-modal-header">
          <h2>help</h2>
          <button @click="$emit('close')" class="help-close-btn" title="Close">×</button>
        </div>

        <div class="help-modal-body" ref="modalBody" tabindex="-1">
          <div class="help-section">
            <h3>text formatting</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><code class="help-syntax">**bold**</code> or <code class="help-syntax">__bold__</code></td>
                  <td><strong>bold</strong></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">*italic*</code> or <code class="help-syntax">_italic_</code></td>
                  <td><em>italic</em></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">***bold italic***</code></td>
                  <td><strong><em>bold italic</em></strong></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">~~strikethrough~~</code></td>
                  <td><s>strikethrough</s></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">\`code\`</code></td>
                  <td><code class="markdown-code">code</code></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">==highlight==</code></td>
                  <td><span class="markdown-highlight">highlight</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">&gt; blockquote</code></td>
                  <td><span class="markdown-quote">blockquote</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">#tagname</code></td>
                  <td><span class="inline-tag">#tagname</span></td>
                </tr>
                <tr>
                  <td><code class="help-syntax">\\*</code></td>
                  <td>escape a special character</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="help-section">
            <h3>command palette</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>K</kbd> / <kbd>Ctrl</kbd> + <kbd>K</kbd></td>
                  <td>open the command palette</td>
                </tr>
                <tr>
                  <td><kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>navigate results</td>
                </tr>
                <tr>
                  <td><kbd>Enter</kbd></td>
                  <td>select</td>
                </tr>
                <tr>
                  <td><kbd>Esc</kbd></td>
                  <td>close</td>
                </tr>
              </tbody>
            </table>
            <p class="help-hint">search pages or run commands (new page, new block, today, settings, help). type <code class="help-syntax">new page &lt;title&gt;</code> to create a page with that title directly.</p>
          </div>

          <div class="help-section">
            <h3>sidebars</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>\\</kbd> / <kbd>Ctrl</kbd> + <kbd>\\</kbd></td>
                  <td>toggle history sidebar</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>\\</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>\\</kbd></td>
                  <td>toggle ai chat panel</td>
                </tr>
                <tr>
                  <td><kbd>Esc</kbd></td>
                  <td>close any open sidebar (when not typing)</td>
                </tr>
              </tbody>
            </table>
            <p class="help-hint">the command palette also has "open/close history" and "open/close ai" entries, which flip labels to match the current state.</p>
          </div>

          <div class="help-section">
            <h3>block editing</h3>
            <table class="help-table">
              <tbody>
                <tr>
                  <td><kbd>Enter</kbd></td>
                  <td>new block</td>
                </tr>
                <tr>
                  <td><kbd>Tab</kbd></td>
                  <td>indent block</td>
                </tr>
                <tr>
                  <td><kbd>Shift</kbd> + <kbd>Tab</kbd></td>
                  <td>outdent block</td>
                </tr>
                <tr>
                  <td><kbd>Backspace</kbd> on empty block</td>
                  <td>delete block</td>
                </tr>
                <tr>
                  <td><kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>navigate between blocks</td>
                </tr>
                <tr>
                  <td><kbd>Alt</kbd> + <kbd>Shift</kbd> + <kbd>↑</kbd> / <kbd>↓</kbd></td>
                  <td>move block up / down</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>⌫</kbd></td>
                  <td>delete block</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>.</kbd> or <kbd>Shift</kbd> + <kbd>F10</kbd></td>
                  <td>open block actions menu</td>
                </tr>
                <tr>
                  <td><kbd>⌘</kbd> + <kbd>Shift</kbd> + <kbd>;</kbd> / <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>;</kbd></td>
                  <td>schedule (set due date / reminder)</td>
                </tr>
                <tr>
                  <td><kbd>Esc</kbd></td>
                  <td>exit editing (keeps focus on block for tabbing)</td>
                </tr>
                <tr>
                  <td>double <kbd>space</kbd> at start</td>
                  <td>indent block (mobile)</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="help-section">
            <h3>block actions</h3>
            <p class="help-hint">click the <strong>⋮</strong> button, <kbd>Tab</kbd> to it, or press <kbd>⌘</kbd>+<kbd>.</kbd> while focused on a block to open the actions menu: indent, outdent, move up/down, create before/after, add to AI context, and delete. inside the menu, use <kbd>↑</kbd><kbd>↓</kbd> to navigate, <kbd>Enter</kbd> to select, <kbd>Esc</kbd> to close.</p>
          </div>
        </div>
      </div>
    </div>
  `,
};
