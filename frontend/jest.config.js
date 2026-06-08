/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: 'jsdom',
  testMatch: [
    '**/tests/**/*.test.js'
  ],
  moduleDirectories: ['node_modules', 'frontend'],
  // Allow testing inline JS by extracting testable functions
  transform: {},
}
