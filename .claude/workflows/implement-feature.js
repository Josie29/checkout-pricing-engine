export const meta = {
  name: 'implement-feature',
  description: 'Implement a Core scope.md component end to end: backend + frontend in parallel against the frozen docs/ specs, then tests, then a spec-compliance review gate.',
  phases: [
    { title: 'Implement', detail: 'backend-executor and frontend-executor run in parallel' },
    { title: 'Test', detail: 'test-writer works from docs/testing-strategy.md, independent of the implementation' },
    { title: 'Review', detail: 'spec-reviewer checks the result against docs/*.md before merge' },
  ],
}

// args: a plain-text description of the Core component to implement, e.g.
// "the POST /price endpoint and naive engine per docs/core-engine-spec.md"

phase('Implement')
const [backend, frontend] = await parallel([
  () => agent(
    `Implement this Core component per docs/scope.md and the backend specs: ${args}`,
    { label: 'backend', agentType: 'backend-executor' }
  ),
  () => agent(
    `Implement this Core component per docs/scope.md and the frontend specs: ${args}`,
    { label: 'frontend', agentType: 'frontend-executor' }
  ),
])

phase('Test')
const tests = await agent(
  `Write tests for this Core component per docs/testing-strategy.md (and docs/optimizer-spec.md's acceptance criteria, if applicable): ${args}`,
  { label: 'tests', agentType: 'test-writer' }
)

phase('Review')
const review = await agent(
  `Review the implementation and tests for this Core component against docs/*.md: ${args}`,
  { label: 'review', agentType: 'spec-reviewer' }
)

return { backend, frontend, tests, review }
