<script setup>
// The product's question (ui.ask / ui.choose), over everything else. It holds the keyboard while it is open
// (focus.js): the focus goes into it, Tab stays in it, the page behind cannot be reached, Escape answers "no", and
// the focus goes back to where it was. Where the answer cannot be undone, the focus starts on "cancel": Enter on a
// question that was not read does not delete anything.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { hold } from '../focus'
import { answer, dialog } from '../ui'

const box = ref(null)
let release = null
onMounted(() => { release = hold(box.value, { first: () => box.value.querySelector('[data-first]') }) })
onBeforeUnmount(() => { if (release) release() })
</script>

<template>
  <Teleport to="body">
    <div class="overlay over-all" @click="answer(dialog.cancel)"></div>
    <div ref="box" class="dialog" role="alertdialog" aria-modal="true" aria-describedby="dialog-text" @keydown.esc.stop="answer(dialog.cancel)">
      <p id="dialog-text">{{ dialog.text }}</p>
      <div v-if="dialog.choices" class="row dialog-acts">
        <button v-for="c in dialog.choices" :key="c.key" :class="c.cls" :data-first="c.focus ? '' : null" @click="answer(c.key)">{{ c.label }}</button>
      </div>
      <div v-else class="row dialog-acts">
        <button :data-first="dialog.danger ? '' : null" @click="answer(false)">{{ $t('common.cancel') }}</button>
        <button :class="dialog.danger ? 'danger solid' : 'primary'" :data-first="dialog.danger ? null : ''" @click="answer(true)">{{ dialog.ok || $t('common.ok') }}</button>
      </div>
    </div>
  </Teleport>
</template>
