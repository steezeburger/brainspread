// Tagged Block Display Component - Shows blocks in tag pages with original DailyNote styling
const TaggedBlockDisplay = {
  props: {
    block: {
      type: Object,
      required: true,
    },
    formatContentWithTags: {
      type: Function,
      required: true,
    },
    formatDate: {
      type: Function,
      required: true,
    },
    toggleBlockTodo: {
      type: Function,
      default: () => {},
    },
  },

  template: `
    <div class="block-wrapper" :data-block-uuid="block.uuid">
      <div class="block">
        <div
          class="block-bullet"
          :class="{ 'todo': block.block_type === 'todo', 'done': block.block_type === 'done' }"
          @click="block.block_type === 'todo' || block.block_type === 'done' ? toggleBlockTodo(block) : null"
        >
          <span v-if="block.block_type === 'todo'">☐</span>
          <span v-else-if="block.block_type === 'done'">☑</span>
          <span v-else>•</span>
        </div>
        <div class="block-content-display" :class="{ 'completed': block.block_type === 'done' }">
          <div class="block-meta">
            <span class="page-title">{{ block.page_type === 'daily' ? formatDate(block.page_title) : block.page_title }}</span>
            <span v-if="block.page_date" class="page-date">{{ formatDate(block.page_date) }}</span>
          </div>
          <div v-html="formatContentWithTags(block.content, block.block_type)" class="block-text"></div>
        </div>
      </div>
    </div>
  `,
};

// Make it globally available
window.TaggedBlockDisplay = TaggedBlockDisplay;
