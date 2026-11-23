<script setup>
// "Software update" on the about page: one card, its parts one under the other and parted by a rule - the state as a
// badge with the version that runs and the one it is about side by side, and the actions valid in it (UpdateStatus,
// the card's centre), the update settings as a summary that opens a compact editor (UpdateSettings), and "Advanced"
// (UpdateAdvanced: the runtime details, by hand, how it works), closed on every load. Nothing side by side but the two
// versions, which hold the same. It does nothing itself: actions (`act`) go to the page, and the settings are saved
// by the page's `save`.
import { ref } from 'vue'
import UpdateAdvanced from './UpdateAdvanced.vue'
import UpdateSettings from './UpdateSettings.vue'
import UpdateStatus from './UpdateStatus.vue'

defineProps({
  model: { type: Object, required: true },          // updateState(...)
  about: { type: Object, required: true },          // GET /api/about
  status: { type: Object, default: null },          // GET /api/system/update as it came
  changelog: { type: Array, default: () => [] },    // the versions this copy's own changelog has
  save: { type: Function, required: true },         // the settings that changed => truthy once saved (UpdateSettings)
})
const emit = defineEmits(['act'])

const advanced = ref(false)
</script>

<template>
  <section class="card up-sec" :aria-label="$t('about.softwareUpdate')">
    <UpdateStatus :model="model" :changelog="changelog" @act="emit('act', $event)" />
    <div class="up-part">
      <UpdateSettings :policy="model.policy" :kind="model.kind" :save="save" />
    </div>
    <div class="up-part up-part-adv">
      <UpdateAdvanced v-model:open="advanced" :about="about" :status="status" />
    </div>
  </section>
</template>
