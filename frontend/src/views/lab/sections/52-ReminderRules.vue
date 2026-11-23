<script setup>
// Lab: the reminders of a kind of calendar item - several, none, an item of a whole day, disabled, and a narrow box where
// the chips wrap. The value under each is what would be stored (minutes before). Every value is made up.
import { ref } from 'vue'
import ReminderRules from '../../../components/ReminderRules.vue'

const interview = ref([1440, 30])
const none = ref([])
const allDay = ref([2880, 0])
const many = ref([10080, 2880, 1440, 120, 30, 0])
</script>

<template>
  <p class="lab-note">× removes (the focus moves to the next ×, or to +); + opens the usual choices (pressed: chosen; pressing again removes) and a custom amount. Stored: <b data-t="rr-interview">{{ JSON.stringify(interview) }}</b></p>
  <div class="lab-row" data-t="rr-row"><ReminderRules v-model="interview" label="Interview" data-t="rr-interview-field" /></div>
  <p class="lab-note">No reminder. Stored: <b data-t="rr-none">{{ JSON.stringify(none) }}</b></p>
  <div class="lab-row"><ReminderRules v-model="none" label="Follow-up" /></div>
  <p class="lab-note">An item of a whole day: reminded in the morning, whole days apart. Stored: <b>{{ JSON.stringify(allDay) }}</b></p>
  <div class="lab-row"><ReminderRules v-model="allDay" label="Application deadline" all-day /></div>
  <p class="lab-note">Disabled; and many in a box of 260px (the chips wrap).</p>
  <div class="lab-row"><ReminderRules :model-value="[1440]" label="Offer response" disabled /></div>
  <div class="lab-box" style="width: 260px; max-width: 100%"><ReminderRules v-model="many" label="Assessment" /></div>
</template>
