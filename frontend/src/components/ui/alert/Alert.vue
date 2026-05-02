<script setup>
import { computed } from "vue"
import { cva } from "class-variance-authority"
import { cn } from "@/lib/utils"

const props = defineProps({
  variant: { type: String, default: "default" },
  class: { type: [String, Array, Object], default: "" },
})

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm [&>svg+div]:translate-y-[-3px] [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg]:text-foreground [&>svg~*]:pl-7",
  {
    variants: {
      variant: {
        default: "bg-background text-foreground",
        destructive:
          "border-destructive/50 bg-destructive/10 text-destructive [&>svg]:text-destructive dark:border-destructive",
        success:
          "border-success/40 bg-success/10 text-success [&>svg]:text-success",
        warning:
          "border-warning/40 bg-warning/10 text-warning [&>svg]:text-warning",
      },
    },
    defaultVariants: { variant: "default" },
  },
)

const classes = computed(() => cn(alertVariants({ variant: props.variant }), props.class))
</script>

<template>
  <div :class="classes" role="alert">
    <slot />
  </div>
</template>
