// preinstall guard: the frontend is managed only with pnpm (see CONTRIBUTING.md).
// `only-allow` cannot be used through `pnpm dlx` because dlx rewrites npm_config_user_agent,
// so this checks the user agent of the package manager that started the install directly.
const userAgent = process.env.npm_config_user_agent ?? ''
if (!userAgent.startsWith('pnpm/')) {
  const detected = userAgent.split(' ')[0] || 'an unknown package manager'
  process.stderr.write(
    `\nerror: the frontend is managed only with pnpm (detected ${detected}).\n` +
      '       Install pnpm from https://pnpm.io/installation, then run `pnpm install`.\n\n',
  )
  process.exit(1)
}
