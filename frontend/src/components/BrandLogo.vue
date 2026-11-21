<script setup>
// The whole logo, as it was drawn, in the page's own colours.
// logo-full.svg (the README's) is a picture with its dark blue painted in. It is the same picture here, in two parts
// made from it (scripts are not needed at run time): logo-ink.png - everything that was dark blue, used as a mask
// that is filled with the text colour - and logo-accent.png, the cyan, which stays as it is.
</script>

<template>
  <span class="logo" role="img" aria-label="AutoApply"><span class="logo-ink" :style="{ maskImage: 'url(logo-ink.png)', WebkitMaskImage: 'url(logo-ink.png)' }"></span><img class="logo-accent" :src="'logo-accent.png'" alt="" /></span>
</template>
