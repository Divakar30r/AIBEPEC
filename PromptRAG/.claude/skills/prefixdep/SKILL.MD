---
name: prefixdep
description: Rename the imported names (classes, functions, constants) of a dependency from requirements.txt with a given prefix, so code from that library is easy to tell apart when reading. Example - module langchain_text_splitters with prefix LC turns Language into LC_Language and RecursiveCharacterTextSplitter into LC_RecursiveCharacterTextSplitter.
argument-hint: <module> <PREFIX>
disable-model-invocation: true
---

# PrefixDep

Arguments received: `$ARGUMENTS` (module name, then prefix)

1. Confirm the module's package is listed in `requirements.txt`. Package names use hyphens and module names use underscores (`langchain-text-splitters` is imported as `langchain_text_splitters`). If it is not listed, say so and stop.
2. Find every Python file in the project (skip `.venv`) that imports from the module.
3. In each file, rename by aliasing the import, never by editing the library:
   - `from module import Name` becomes `from module import Name as PREFIX_Name`
   - `import module` becomes `import module as PREFIX`, and usages `module.Name` become `PREFIX.Name`
4. Update every use of those names in the file to the prefixed form, including calls and constants. Do not touch same-named identifiers that do not come from the module, or text inside strings and comments.
5. Keep the prefix and the original name joined by an underscore, with the original capitalisation (`LC_Language`).
6. Report which files and names changed. Leave tests alone unless they import from the module directly.
