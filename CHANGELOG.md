# Changelog

<!-- insertion marker -->
## [v0.3.2](https://github.com/frostming/unearth/releases/tag/0.3.2) (2022-05-28)

### Bug Fixes

- Add ending slash to the project index URL. [#7](https://github.com/frostming/unearth/issues/7)


## [v0.3.1](https://github.com/frostming/unearth/releases/tag/0.3.1) (2022-05-27)

### Bug Fixes

- Fix a bug that local source wheels are moved to the destination. [#6](https://github.com/frostming/unearth/issues/6)


## [v0.3.0](https://github.com/frostming/unearth/releases/tag/0.3.0) (2022-05-27)

### Features & Improvements

- Export more methods and variables in the top package. [#4](https://github.com/frostming/unearth/issues/4)
- Rename parameter `dest` to `location` in `PackageFinder.download_and_unpack()` and VCS methods. [#5](https://github.com/frostming/unearth/issues/5)
- `PackageFinder.download_and_unpack` gets a default value for `download_dir`, where a temporary dir will be created for downloading. [#5](https://github.com/frostming/unearth/issues/5)

### Bug Fixes

- Fix the type annotations across the entire project. [#4](https://github.com/frostming/unearth/issues/4)

### Removals and Deprecations

- Remove the integration of `requests-cache`, downstream projects need to handle the caches themselves by passing a custom subclass of `PyPISession` to the `PackageFinder`. [#4](https://github.com/frostming/unearth/issues/4)


## [v0.2.0](https://github.com/frostming/unearth/releases/tag/0.2.0) (2022-05-24)

### Features & Improvements

- Implement the logic for downloading a file link to local. [#3](https://github.com/frostming/unearth/issues/3)
- Support VCS requirements for git, subversion, mercurial and bazaar. [#3](https://github.com/frostming/unearth/issues/3)
