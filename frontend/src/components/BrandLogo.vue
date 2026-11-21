<script setup>
// The whole logo - the mark standing for the "A", then "utoApply" - drawn in the page's own colours.
// logo-full.svg (the README's) is a picture with its dark blue painted in: on a dark page it would need a light plate
// behind it. Here the mark is the vector one, with its dark parts taking the text colour, and the name is text.
import raw from '../../public/logo-mark.svg?raw'

const DARK = /fill="#(03142A|060F1F|172236|182336|192034|1C2739)"/gi      // the mark's dark blue: the page's text colour instead
const EDGE = /fill="#(DEE2E6|DFE2E5|E0E4E8|E3E6EA)"/gi                    // light slivers left from its white background: not drawn
const mark = raw.replace(/<\?xml[^>]*\?>/, '').replace(DARK, 'fill="currentColor"').replace(EDGE, 'fill="none"')
  .replace(/<svg /, '<svg aria-hidden="true" focusable="false" ').replace(/ width="\d+" height="\d+"/, '')
</script>

<template>
  <span class="logo" role="img" aria-label="AutoApply"><span class="logo-mark" v-html="mark"></span><span class="logo-name" aria-hidden="true">utoApply</span></span>
</template>
