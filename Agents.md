# Agents

## Development And Testing Workflow Constraint

For every future code adjustment in this project:

1. Make all code changes in the local git repository first.
2. Commit and push the changes to the remote repository.
3. Connect to the Raspberry Pi over SSH and pull the latest changes in its `develop/Rover` checkout.
4. Run validation/tests on the Raspberry Pi environment after pulling.
