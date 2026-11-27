/**
 * dsh-comsol - registers the COMSOL agent skills.
 *
 * Two skills ship inside this bundle (both are optional workflows - the plugin
 * toggle is the switch for all of them):
 *   assets/comsol-dsh/   drive COMSOL end to end (SKILL.md + scripts + tests)
 *   assets/cfd-web3d/    turn CFD results into web 3D (glTF/GLB + three.js)
 *   assets/engine/       the vendored comsol-mcp checkout (src/ + tests/)
 *
 * The skill name/description are parsed from the SKILL.md frontmatter at load
 * time, so the plugin manifest and the skill body can never drift apart -
 * SKILL.md is the single source of truth. `get` re-reads the body, so an
 * on-disk update is picked up after a plugin reload.
 *
 * Toggling this plugin in the DSH plugin panel enables/disables the skill for
 * every workspace at once - the plugin panel is the switch.
 */

import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const PROVIDER_NAME = 'dsh-comsol'

/** Every skill this bundle ships; add an entry here to expose another folder. */
const SKILLS = [
  {
    dir: 'comsol-dsh',
    fallback: {
      name: 'comsol-dsh',
      description:
        'Drive COMSOL Multiphysics models end to end. Use when the user asks to ' +
        'run, modify, solve, or inspect a COMSOL (.mph) model.',
    },
  },
  {
    dir: 'cfd-web3d',
    fallback: {
      name: 'cfd-web3d',
      description:
        'Turn CFD/CAE results (ANSYS, COMSOL, ParaView) into web 3D. Use when the ' +
        'user asks to put streamlines or contours on a web page, make an ' +
        'interactive 3D view, or export glTF/GLB.',
    },
  },
].map((s) => {
  const dirUrl = new URL('./assets/' + s.dir + '/', import.meta.url)
  return {
    ...s,
    skillUrl: new URL('SKILL.md', dirUrl),
    resourceBase: { kind: 'directory', path: fileURLToPath(dirUrl) },
  }
})

/** Minimal YAML frontmatter reader: top-level `key: value` lines. */
function parseFrontmatter (text) {
  const out = {}
  if (!text.startsWith('---')) return out
  const end = text.indexOf('\n---', 3)
  if (end < 0) return out
  for (const line of text.slice(3, end).split('\n')) {
    const m = /^([A-Za-z][\w-]*):\s*(.*)$/.exec(line.trim())
    if (m && out[m[1]] === undefined) out[m[1]] = m[2].trim()
  }
  return out
}

async function skillMeta (skill) {
  try {
    const text = await readFile(skill.skillUrl, 'utf8')
    const fm = parseFrontmatter(text)
    return {
      name: fm.name || skill.fallback.name,
      description: fm.description || skill.fallback.description,
    }
  } catch {
    return { ...skill.fallback }
  }
}

const INVOCATION = { modelInvocable: true, userInvocable: true }

/**
 * Precedence this provider's candidates carry in the DSH skill registry.
 * Every candidate must expose a finite numeric rank, and lower ranks win
 * duplicate skill names across providers. 600 is BUNDLED_SKILL_RANK - the
 * rank the registry reserves for packaged skill providers.
 */
const SKILL_RANK = 600

const provider = {
  name: PROVIDER_NAME,
  async list () {
    const out = []
    for (const skill of SKILLS) {
      if (!existsSync(fileURLToPath(skill.skillUrl))) continue
      const meta = await skillMeta(skill)
      out.push({
        name: meta.name,
        description: meta.description,
        invocation: INVOCATION,
        provider: PROVIDER_NAME,
        source: 'bundled',
        rank: SKILL_RANK,
        resourceBase: skill.resourceBase,
        locator: fileURLToPath(skill.skillUrl),
      })
    }
    return out
  },
  async get (candidate) {
    const wanted = candidate?.name
    const skill = SKILLS.find((s) => s.dir === wanted) ||
      SKILLS.find((s) => existsSync(fileURLToPath(s.skillUrl)) &&
        (s.fallback.name === wanted || s.dir === wanted)) ||
      SKILLS[0]
    const meta = await skillMeta(skill)
    return {
      name: candidate?.name || meta.name,
      description: meta.description,
      invocation: INVOCATION,
      provider: PROVIDER_NAME,
      source: 'bundled',
      resourceBase: skill.resourceBase,
      content: await readFile(skill.skillUrl, 'utf8'),
    }
  },
}

/** Cordis plugin name. */
export const name = 'comsol'
/** Services this plugin requires; the skill registry injects them. */
export const inject = ['skills']

/** @param {any} ctx */
export function apply (ctx) {
  if (!SKILLS.some((s) => existsSync(fileURLToPath(s.skillUrl)))) {
    ctx?.logger?.warn?.('dsh-comsol: no bundled SKILL.md found; skills not registered')
    return
  }
  ctx.skills.registerProvider(() => provider)
}
