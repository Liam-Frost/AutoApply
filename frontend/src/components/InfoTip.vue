<script setup>
// A small (i) beside a title or a state: what it says shows in the program's tooltip on hover and on keyboard focus,
// and a press shows or hides it (a finger cannot hover). For a sentence; anything longer, or with something to press,
// is a Popover.
import Icon from './Icon.vue'

defineProps({ text: { type: String, required: true }, label: { type: String, default: '' }, placement: { type: String, default: 'top' } })
</script>

<template>
  <!-- (the click stays here: an (i) in a row that opens on a click does not open the row) -->
  <button v-tip.press="{ text, placement }" type="button" class="info-tip" :aria-label="label || $t('common.moreInfo')" @click.stop><Icon name="info" /></button>
</template>
