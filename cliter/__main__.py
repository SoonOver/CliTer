"""CliTer entrypoint."""
import sys

def main():
    from cliter.app import CliTerApp
    app = CliTerApp()
    app.run()

if __name__ == "__main__":
    main()
