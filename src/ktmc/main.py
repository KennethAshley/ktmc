import bittensor as bt
import logging
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Bot:
    def __init__(self, wallet, subtensor, netuid=8, stake_amount=0.5):
        self.wallet = wallet
        self.subtensor = subtensor
        self.netuid = netuid
        self.stake_amount = stake_amount


    async def wait_for_next_epoch(self):
        try:
            query_result = self.subtensor.query_map_subtensor("Tempo")
            tempo_dict = {}
            for k, v in query_result:
                key = k if isinstance(k, int) else k.value if hasattr(k, 'value') else int(k)
                tempo_dict[key] = v

            if self.netuid not in tempo_dict:
                raise Exception(f"Netuid {self.netuid} not found in tempo map")

            tempo_obj = tempo_dict[self.netuid]
            tempo = int(tempo_obj.value) if hasattr(tempo_obj, 'value') else int(tempo_obj)
            logger.info(f"Tempo for subnet {self.netuid} = {tempo}")

            interval = tempo + 1
            current_block = self.subtensor.get_current_block()
            last_epoch = current_block - 1 - (current_block + self.netuid + 1) % interval
            next_tempo_block_start = last_epoch + interval

            logger.info(f"Current block: {current_block}")
            logger.info(f"Next epoch block: {next_tempo_block_start}")
            logger.info(f"Blocks until next epoch: {next_tempo_block_start - current_block}")

            while current_block < next_tempo_block_start - 3:
                await asyncio.sleep(1)
                current_block = self.subtensor.get_current_block()
                if (current_block % 10) == 0:
                    logger.info(f"Current block: {current_block}, Blocks until epoch: {next_tempo_block_start - current_block}")

            return next_tempo_block_start

        except Exception as e:
            logger.error(f"Error determining next epoch: {e}")
            raise

async def run_continously():
    wallet = bt.wallet(name='default')
    subtensor = bt.subtensor(network="finney")

    bot = Bot(wallet, subtensor, netuid=8, stake_amount=0.5)

    while True:
        try:
            await bot.execute_strategy()

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Error in Bot loop: {e}")
            await asyncio.sleep(60)


def main():
    try:
        asyncio.run(run_continously())

    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Error in main: {e}")
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
