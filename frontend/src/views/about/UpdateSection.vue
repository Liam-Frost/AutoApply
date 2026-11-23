<script setup>
// "Software update" on the about page: one card, its parts one under the other and parted by a rule - the state with
// its facts and the actions valid in it (UpdateStatus), the update settings (UpdateSettings), and "Advanced"
// (UpdateAdvanced: by hand, how it works, the runtime details), closed on every load. Nothing side by side: each part is
// as tall as what it holds. It does nothing itself: actions (`act`) and settings (`save`) go to the page.
import { ref } from 'vue'
import CardHead from '../../components/CardHead.vue'
import UpdateAdvanced from './UpdateAdvanced.vue'
import UpdateSettings from './UpdateSettings.vue'
import UpdateStatus from './UpdateStatus.vue'

defineProps({
  model: { type: Object, required: true },          // updateState(...)
  about: { type: Object, required: true },          // GET /api/about
  status: { type: Object, default: null },          // GET /api/system/update as it came
  changelog: { type: Array, default: () => [] },    // the versions this copy's own changelog has
})
const emit = defineEmits(['act', 'save'])

const advanced = ref(false)
const adv = ref(null)
</script>

<template>
  <section class="card up-sec" aria-labelledby="up-sec-title">
    <CardHead id="up-sec-title" :title="$t('about.softwareUpdate')" />
    <UpdateStatus :model="model" :changelog="changelog" @act="emit('act', $event)" @show-command="adv.showCommand()" />
    <div class="up-part">
      <UpdateSettings :policy="model.policy" @save="(key, value) => emit('save', key, value)" />
    </div>
    <div class="up-part up-part-adv">
      <UpdateAdvanced ref="adv" v-model:open="advanced" :about="about" :status="status" />
    </div>
  </section>
</template>
